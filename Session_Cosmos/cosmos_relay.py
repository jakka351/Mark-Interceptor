#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║  COSMOS RELAY · Session Cosmos Bridge Server  (v2.0)          ║
║                                                               ║
║  Receives Facebook blob captures from the browser userscript  ║
║  and broadcasts them to connected Session Cosmos clients.     ║
║                                                               ║
║  v1.1: Server heartbeat pings every 20s to prevent idle       ║
║        connection drops through NAT/proxies/firewalls.        ║
║  v1.2: --log PATH flag appends every blob to an NDJSON file   ║
║        for direct use with Reflex (offline analysis).         ║
║  v2.0: Accept multi-kind events from userscript v2.0          ║
║        (__kind=request|input|visibility), route definitions,  ║
║        sequence counter on broadcasts, per-kind log stats,    ║
║        health endpoint reports kind-split counts.             ║
║        Fully backward-compatible with userscript v1.0 / v1.1. ║
║                                                               ║
║  Requires: Python 3.7+ (stdlib only, no pip installs)         ║
║  Run:      python cosmos_relay.py                             ║
║         or python cosmos_relay.py --log session.ndjson        ║
║  Stop:     Ctrl+C                                             ║
╚═══════════════════════════════════════════════════════════════╝
"""

import argparse
import asyncio
import base64
import hashlib
import json
import struct
import sys
from datetime import datetime
from pathlib import Path

HOST = "127.0.0.1"
WS_PORT = 8765
HTTP_PORT = 8766
PING_INTERVAL = 20  # seconds between server-initiated pings
READ_TIMEOUT = 300  # max idle time before forcing close (5 min)

# NDJSON capture state (set from CLI). When non-None, every broadcast blob
# is also appended as one JSON line here. Always append — sessions accumulate.
LOG_FILE = None        # type: Optional[TextIO]
LOG_PATH = None        # type: Optional[Path]
LOG_COUNT = 0          # total blobs written this run
# v2.0: per-kind counters for the /health endpoint
KIND_COUNTS = {'request': 0, 'input': 0, 'visibility': 0, 'other': 0}
# v2.0: monotonic server-side sequence id, stamped on every broadcast
BROADCAST_SEQ = 0

class C:
    CYAN = "\033[96m"
    PINK = "\033[95m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg, color=C.CYAN):
    print(f"{C.GRAY}{ts()}{C.RESET} {color}{msg}{C.RESET}", flush=True)

def banner():
    print(f"""{C.CYAN}
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ██████  ██████  ███████ ███    ███  ██████  ███████         ║
║  ██      ██    ██ ██      ████  ████ ██    ██ ██              ║
║  ██      ██    ██ ███████ ██ ████ ██ ██    ██ ███████         ║
║  ██      ██    ██      ██ ██  ██  ██ ██    ██      ██         ║
║   ██████  ██████  ███████ ██      ██  ██████  ███████         ║
║                                                               ║
║                     R E L A Y   v 2 . 0                       ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝{C.RESET}
    {C.GRAY}Session Cosmos telemetry bridge{C.RESET}
    {C.DIM}WebSocket out:{C.RESET}  {C.CYAN}ws://{HOST}:{WS_PORT}{C.RESET}
    {C.DIM}HTTP ingest:{C.RESET}   {C.PINK}http://{HOST}:{HTTP_PORT}/ingest{C.RESET}
    {C.DIM}Heartbeat:{C.RESET}     {C.GRAY}ping every {PING_INTERVAL}s (keeps NAT/proxies happy){C.RESET}

    {C.GRAY}Press Ctrl+C to stop.{C.RESET}
""")


WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

class WSClient:
    def __init__(self, reader, writer, client_id):
        self.reader = reader
        self.writer = writer
        self.client_id = client_id
        self.alive = True
        self.last_activity = asyncio.get_event_loop().time()

    async def send_text(self, payload: str):
        if not self.alive:
            return
        try:
            data = payload.encode("utf-8")
            frame = self._make_frame(data, opcode=0x1)
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            self.alive = False

    async def send_ping(self):
        """Send a ping frame. Browsers auto-reply with pong transparently."""
        if not self.alive:
            return
        try:
            frame = self._make_frame(b"cosmos-ping", opcode=0x9)
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            self.alive = False

    def _make_frame(self, data, opcode=0x1):
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(data)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header += struct.pack(">H", length)
        else:
            header.append(127)
            header += struct.pack(">Q", length)
        return bytes(header) + data

    async def close(self):
        self.alive = False
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


clients: "list[WSClient]" = []
next_client_id = [1]


async def ping_loop(client: WSClient):
    """Send a ping every PING_INTERVAL seconds to keep the connection alive."""
    try:
        while client.alive:
            await asyncio.sleep(PING_INTERVAL)
            if not client.alive:
                break
            await client.send_ping()
    except asyncio.CancelledError:
        pass


async def handle_websocket(reader, writer):
    peer = writer.get_extra_info("peername")
    client_id = next_client_id[0]
    next_client_id[0] += 1
    ping_task = None
    client = None

    try:
        # Read HTTP upgrade request
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = await asyncio.wait_for(reader.read(1024), timeout=5)
            if not chunk:
                return
            request += chunk
            if len(request) > 8192:
                return

        headers = {}
        try:
            lines = request.decode("latin-1").split("\r\n")
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
        except Exception:
            return

        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return

        accept = base64.b64encode(
            hashlib.sha1((ws_key + WS_MAGIC).encode()).digest()
        ).decode()

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        writer.write(response.encode())
        await writer.drain()

        client = WSClient(reader, writer, client_id)
        clients.append(client)
        log(f"◉ COSMOS CLIENT #{client_id} CONNECTED  {C.DIM}({peer[0]}:{peer[1]}){C.RESET}  {C.GRAY}[{len(clients)} total]{C.RESET}", C.GREEN)

        # Say hello
        await client.send_text(json.dumps({
            "__type": "hello", "relay": "cosmos_relay", "version": "2.0",
            "ping_interval": PING_INTERVAL,
            "supports_kinds": ["request", "input", "visibility"],
            "broadcast_seq": BROADCAST_SEQ,
        }))

        # Start heartbeat pings
        ping_task = asyncio.create_task(ping_loop(client))

        # Read frames until close
        while client.alive:
            try:
                header = await asyncio.wait_for(reader.readexactly(2), timeout=READ_TIMEOUT)
            except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                break
            b1, b2 = header[0], header[1]
            opcode = b1 & 0x0F
            masked = (b2 & 0x80) != 0
            length = b2 & 0x7F
            if length == 126:
                ext = await reader.readexactly(2)
                length = struct.unpack(">H", ext)[0]
            elif length == 127:
                ext = await reader.readexactly(8)
                length = struct.unpack(">Q", ext)[0]
            if masked:
                mask = await reader.readexactly(4)
                payload = bytearray(await reader.readexactly(length))
                for i in range(length):
                    payload[i] ^= mask[i % 4]
            else:
                payload = await reader.readexactly(length)

            client.last_activity = asyncio.get_event_loop().time()

            if opcode == 0x8:  # close
                break
            if opcode == 0x9:  # ping from client → send pong
                pong = client._make_frame(bytes(payload), opcode=0xA)
                writer.write(pong)
                await writer.drain()
            # opcode 0xA (pong) — browser replying to our ping. Just note activity.

    except Exception as e:
        log(f"websocket error [{client_id}]: {e}", C.YELLOW)
    finally:
        if ping_task:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        if client:
            await client.close()
            if client in clients:
                clients.remove(client)
            log(f"○ COSMOS CLIENT #{client_id} DISCONNECTED  {C.GRAY}[{len(clients)} remaining]{C.RESET}", C.GRAY)


async def broadcast(payload: dict):
    """Log + fan out one payload. v2.0: stamps __relay_seq, tracks __kind counts."""
    global LOG_COUNT, BROADCAST_SEQ

    # v2.0: add a server-side monotonic sequence id. This lets downstream tools
    # (Reflex, reflex_live.html) detect dropped broadcasts and order robustly
    # across client-side clock skew.
    BROADCAST_SEQ += 1
    payload = dict(payload)
    payload['__relay_seq'] = BROADCAST_SEQ

    # v2.0: per-kind accounting
    kind = payload.get('__kind', 'request')
    if kind in KIND_COUNTS:
        KIND_COUNTS[kind] += 1
    else:
        KIND_COUNTS['other'] += 1

    if LOG_FILE is not None:
        try:
            LOG_FILE.write(json.dumps(payload, separators=(',', ':')) + '\n')
            LOG_FILE.flush()  # per-line flush — kill -9 never drops blobs
            LOG_COUNT += 1
        except (OSError, ValueError) as e:
            log(f"log write failed: {e}", C.YELLOW)

    if not clients:
        return 0
    text = json.dumps(payload)
    dead = []
    for c in clients:
        await c.send_text(text)
        if not c.alive:
            dead.append(c)
    for c in dead:
        if c in clients:
            clients.remove(c)
    return len([c for c in clients if c.alive])


async def handle_http(reader, writer):
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5)
        if not request_line:
            return
        try:
            method, path, _ = request_line.decode("latin-1").strip().split(" ", 2)
        except ValueError:
            return

        headers = {}
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
            try:
                k, v = line.decode("latin-1").strip().split(":", 1)
                headers[k.strip().lower()] = v.strip()
            except ValueError:
                continue

        if method == "OPTIONS":
            writer.write(
                b"HTTP/1.1 204 No Content\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n"
                b"Access-Control-Allow-Headers: Content-Type\r\n"
                b"Access-Control-Max-Age: 86400\r\n\r\n"
            )
            await writer.drain()
            return

        if method == "GET" and path.startswith("/health"):
            body = json.dumps({
                "status": "ok",
                "clients": len(clients),
                "version": "2.0",
                "ports": {"ws": WS_PORT, "http": HTTP_PORT},
                "log": {
                    "enabled": LOG_FILE is not None,
                    "path": str(LOG_PATH) if LOG_PATH else None,
                    "written": LOG_COUNT,
                },
                "kinds": dict(KIND_COUNTS),
                "broadcast_seq": BROADCAST_SEQ,
            }).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            await writer.drain()
            return

        if method == "POST" and path.startswith("/ingest"):
            length = int(headers.get("content-length", "0"))
            if length <= 0 or length > 500_000:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await writer.drain()
                return
            body = await reader.readexactly(length)
            try:
                blob = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await writer.drain()
                return

            count = await broadcast(blob)

            # v2.0 log line adapts to event kind (request vs input vs visibility)
            kind = blob.get("__kind", "request")
            if kind == "request":
                req = blob.get("__req", "?")
                crn = (blob.get("__crn") or "?").replace("comet.fbweb.", "").replace("comet.bizweb.", "biz.")
                friendly = blob.get("fb_api_req_friendly_name", "")
                friendly_short = (friendly[:32] + "…") if len(friendly) > 32 else friendly
                lat = blob.get("__latency_ms")
                lat_str = f"{lat}ms" if lat else "     "
                log(
                    f"▸ BLOB  req={C.BOLD}{str(req):>6}{C.RESET}  "
                    f"route={C.CYAN}{crn:<28}{C.RESET}  "
                    f"op={C.YELLOW}{friendly_short:<33}{C.RESET}  "
                    f"{C.DIM}{lat_str:>6}{C.RESET}  ↗ {count} client(s)",
                    C.PINK,
                )
            elif kind == "input":
                ev = blob.get("__event", "?")
                v = blob.get("__velocity_px_per_s") or blob.get("__delta_px", "")
                log(f"▸ INPUT {ev}  {v}  ↗ {count} client(s)", C.GREEN)
            elif kind == "visibility":
                ev = blob.get("__event", "?")
                log(f"▸ VIS   {ev}  ↗ {count} client(s)", C.YELLOW)
            else:
                log(f"▸ ???   kind={kind}  ↗ {count} client(s)", C.GRAY)

            resp = json.dumps({"ok": True, "broadcast_to": count, "relay_seq": BROADCAST_SEQ}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Content-Length: " + str(len(resp)).encode() + b"\r\n\r\n" + resp
            )
            await writer.drain()
            return

        writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()

    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        pass
    except Exception as e:
        log(f"http error: {e}", C.YELLOW)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main(log_path: "Optional[Path]" = None):
    global LOG_FILE, LOG_PATH

    banner()

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            LOG_FILE = log_path.open('a', encoding='utf-8', buffering=1)
            LOG_PATH = log_path
            existing = 0
            try:
                # Count existing lines so the user knows what they're appending to
                with log_path.open('r', encoding='utf-8') as f:
                    for _ in f:
                        existing += 1
                # Subtract the one we just may have added in the count loop... actually no,
                # we haven't written anything yet. The count is purely pre-existing.
            except Exception:
                pass
            log(f"✎ NDJSON capture enabled → {C.BOLD}{log_path}{C.RESET}  "
                f"{C.GRAY}(appending; {existing} existing line(s)){C.RESET}", C.PINK)
        except OSError as e:
            log(f"error: could not open log file {log_path}: {e}", C.YELLOW)
            return 1

    ws_server = await asyncio.start_server(handle_websocket, HOST, WS_PORT)
    http_server = await asyncio.start_server(handle_http, HOST, HTTP_PORT)
    log(f"WebSocket server listening on {HOST}:{WS_PORT}", C.GREEN)
    log(f"HTTP ingest listening on {HOST}:{HTTP_PORT}", C.GREEN)
    log(f"{C.BOLD}Ready. Open session_cosmos.html and click CONNECT.{C.RESET}", C.CYAN)
    print()

    try:
        async with ws_server, http_server:
            await asyncio.gather(
                ws_server.serve_forever(),
                http_server.serve_forever(),
            )
    finally:
        if LOG_FILE is not None:
            try:
                LOG_FILE.close()
            except Exception:
                pass
            log(f"✎ log closed · {LOG_COUNT} blob(s) written this session", C.PINK)


def parse_args():
    p = argparse.ArgumentParser(
        prog="cosmos_relay",
        description="Session Cosmos telemetry relay — WebSocket broadcaster + NDJSON recorder.",
    )
    p.add_argument(
        "--log", type=Path, default=None, metavar="PATH",
        help="Append every captured blob as one JSON line to this file. "
             "Feeds directly into Reflex. Appends if the file already exists.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        if sys.platform == "win32":
            import os
            os.system("")
        asyncio.run(main(log_path=args.log))
    except KeyboardInterrupt:
        print(f"\n{C.GRAY}relay shut down{C.RESET}")
