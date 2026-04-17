# SESSION·COSMOS

> *A digital archaeology instrument for reconstructing browsing sessions as navigable 3D architecture.*

Session Cosmos captures the hidden telemetry fields that Facebook/Meta attaches to every request (`__req`, `__crn`, `__ccg`, `__spin_t`, etc.) and rebuilds them as a living 3D cosmos you can fly through. Every request becomes a glowing node at an altitude determined by which Facebook surface it came from. Bursts of activity form dense constellations. Idle gaps stretch into voids. Bundle revision changes cut vertical seismic lines through the scene.

---

## The kit

| File | What it is | Where it runs |
|---|---|---|
| `session_cosmos.html` | The 3D visualizer itself. Standalone HTML, no build step. | Your browser (double-click to open) |
| `cosmos_relay.py` | Tiny WebSocket/HTTP bridge server. Python stdlib only, no pip installs. | A terminal window on your machine |
| `facebook-interceptor.user_1.js` | Userscript v1.1 — captures blobs **plus** `fb_api_req_friendly_name` for activity decoding. | Tampermonkey extension in your browser |
| `facebook-interceptor.user.js` | Userscript v1.0 (legacy, blobs only — prefer v1.1). | Tampermonkey extension |

---

## Quick start — three terminals, three minutes

### 1. Run the relay

```bash
python cosmos_relay.py                         # basic
python cosmos_relay.py --log session.ndjson    # also append every blob to NDJSON for Reflex
```

You'll see a neon banner and two messages confirming the WebSocket and HTTP servers are up. Leave this running.

Sanity check: `curl http://127.0.0.1:8766/health` returns JSON — if `--log` is on, you'll see `{"log": {"enabled": true, "path": "...", "written": N}}`.

### 2. Open the visualizer

Double-click `session_cosmos.html`. It opens in your default browser with a pre-built synthetic session so the cosmos looks alive on first launch.

Click the **STREAM** tab on the right ingest panel, make sure the URL is `ws://localhost:8765`, and click **CONNECT**. The status indicator should turn cyan and say `STREAM LIVE`.

### 3. Install the userscript

Install the [Tampermonkey](https://www.tampermonkey.net/) browser extension (Chrome, Firefox, Edge, Safari, Brave — free, no account).

1. Click the Tampermonkey icon → **Create a new script**
2. Delete the template and paste the entire contents of `facebook-interceptor.user_1.js` (the v1.1 file)
3. Save (Ctrl/Cmd + S)
4. Make sure it's toggled **on** in the Tampermonkey dashboard

Now visit [facebook.com](https://www.facebook.com). You should see a floating neon HUD in the top-right corner — that's the interceptor. Scroll around, click between Home, Profile, Messenger, etc.

Switch back to the Session Cosmos tab and **watch new nodes spawn in real-time** as your browsing generates telemetry. The terminal running the relay will log every captured blob.

---

## How it works

```
┌────────────────┐       ┌──────────────┐        ┌─────────────────┐
│  Facebook tab  │       │ Python relay │        │ Session Cosmos  │
│  (Tampermonkey │──POST─▶│ (cosmos_     │──WS──▶│ (session_       │
│   interceptor) │       │  relay.py)   │        │  cosmos.html)   │
└────────────────┘       └──────────────┘        └─────────────────┘
    captures blobs       broadcasts to all        renders in 3D
    from fetch/XHR       connected clients        with spawn FX
                         + optional NDJSON log
```

The interceptor hooks `fetch`, `XMLHttpRequest`, and `navigator.sendBeacon` on any Facebook/Messenger page. Every request body is inspected for the known blob fields. When a match is found, it's extracted and POSTed to `http://127.0.0.1:8766/ingest`. The relay then broadcasts the JSON payload to every connected WebSocket client, and (with `--log`) appends it to an NDJSON file for later analysis with [Reflex](../Reflex/README.md).

---

## Controls inside Session Cosmos

- **Drag** to orbit the cosmos
- **Scroll** to zoom
- **Click any node** to see full telemetry
- **ORBIT / TOPDOWN / REPLAY** (top-right) — camera modes
- **REPLAY** shows a scrubber — drag through time to fly along your session like a rollercoaster
- **MANUAL** tab — paste one or many blobs from the clipboard (separate with blank lines or `===`)
- **LIVE PASTE** tab — auto-ingest on pause
- **STREAM** tab — connect to the relay for real-time streaming

---

## Encoding legend

| Visual | Data |
|---|---|
| Node altitude | Facebook surface (HOME / PROFILE / MESSENGER / etc.) |
| Horizontal position | Time / request sequence |
| Node size | Big = anchored real data · small = reconstructed |
| Node color | Surface color (cyan for HOME, pink for PROFILE, amber for MESSENGER, etc.) |
| Ringed node | Real anchored blob |
| Edge color | Connection quality at that moment (GOOD / POOR / BAD etc.) |
| Pink dashed vertical line | Bundle revision deploy detected mid-session |
| Pulsing node at front | The most recent / "now" event |

---

## Privacy notes

- **Nothing leaves your machine.** The relay binds to `127.0.0.1` — localhost only. No outside network can reach it.
- The userscript sends captured blobs **only to the local relay**. It does not phone home.
- The visualizer **hides sensitive tokens** (`fb_dtsg`, `lsd`, `jazoest`) from the detail view by default.
- These tokens are session-scoped anti-CSRF values. Don't share screenshots of the raw telemetry panel with untrusted people.

---

## Troubleshooting

**Relay says `RELAY UNREACHABLE` in the HUD.**
Is `cosmos_relay.py` actually running? Check the terminal. If you see the banner and "Ready" line, it's up. Try opening `http://127.0.0.1:8766/health` — you should see JSON.

**HUD appears but capture count stays at 0.**
The page might not have generated any telemetry yet. Try clicking around — switching between Home and Profile is a guaranteed trigger. If still zero, open browser devtools console and look for `[SESSION COSMOS] Interceptor armed`.

**Visualizer shows "CONNECTION ERROR".**
The relay isn't running, or something else is using port 8765. On Windows: `netstat -ano | findstr 8765`. Stop whatever holds it and restart the relay.

**Getting a CORS error in the browser console.**
Make sure you're POSTing to `http://127.0.0.1:8766/ingest` (not `localhost` — some browsers treat them as different origins).

**Tampermonkey says "GM_xmlhttpRequest not allowed".**
Open the userscript in Tampermonkey's editor and check that `@grant GM_xmlhttpRequest` and `@connect 127.0.0.1` are in the header.

---

## Changing ports

Edit `cosmos_relay.py`:
```python
WS_PORT = 8765    # change these
HTTP_PORT = 8766
```
Then update the userscript:
```javascript
const RELAY_URL = 'http://127.0.0.1:8766/ingest';  // match HTTP_PORT
```
And in the Session Cosmos STREAM tab, update the WS URL to match `WS_PORT`.

---

## Piping into Reflex

Run the relay with `--log` to get an NDJSON file you can feed into Reflex for offline portrait analysis:

```bash
python cosmos_relay.py --log ../Reflex/my_session.ndjson
# browse Facebook for a while, Ctrl+C when done
cd ../Reflex && python reflex.py my_session.ndjson -o my_report.html
```

---

## Ethical use

This tool captures **your own** browsing telemetry from your own browser for personal visualization. Don't use it to intercept or analyze anyone else's traffic. Don't share captured blobs publicly — they contain session tokens. Use responsibly.
