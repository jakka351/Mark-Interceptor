# Mark-Interceptor
Watching the reflection of Facebook watching us. A way to look into the algorithm and it's grip o'er us.

> **Capture your own Facebook session telemetry. Watch it render as a 3D cosmos. Then let the mirror tell you who you are when the algorithm is watching.**

A two-part, localhost-only toolkit for algorithmic self-research:

- **Session Cosmos** — captures the hidden telemetry fields Facebook/Meta attaches to every request, and renders them live as a navigable 3D space you can fly through.
- **Reflex** — reads the captured stream back offline and produces a single self-contained HTML portrait of the feedback loop between *you* and the ranking algorithm.

<sup>
Pure Python stdlib on the backend. Zero build step on the frontend. Nothing leaves your machine. No Facebook API. No third-party data. No calls home.
</sup>

<img width="929" height="381" alt="image" src="https://github.com/user-attachments/assets/cb280570-c38e-45a4-bc46-5c2266c97283" />




---

## Table of contents

1. [What you get](#what-you-get)
2. [What it reveals](#what-it-reveals)
3. [Quick start](#quick-start-five-minutes)
4. [Architecture](#architecture)
5. [Session Cosmos in depth](#session-cosmos-in-depth)
6. [Reflex in depth](#reflex-in-depth)
7. [Repository layout](#repository-layout)
8. [Privacy and ethics](#privacy-and-ethics)
9. [Troubleshooting](#troubleshooting)
10. [Platform notes](#platform-notes)
11. [Roadmap](#roadmap)
12. [Contributing](#contributing)
13. [License](#license)

---

## What you get

<img width="1904" height="888" alt="image" src="https://github.com/user-attachments/assets/0b9fbec8-0277-4b44-9a89-8b8a4a2b3af8" />


| Component | What it does | Runs in | Inputs | Outputs |
|---|---|---|---|---|
| `cosmos_relay.py` | WebSocket broadcaster + HTTP ingest + optional NDJSON recorder | A terminal (Python 3.7+) | HTTP POSTs from the userscript | Live WS stream + `session.ndjson` |
| `session_cosmos.html` | 3D visualizer (Three.js, single file, no build step) | Your browser | WS stream from the relay | A flyable cosmos |
| `facebook-interceptor.user_1.js` | Userscript v1.1 — hooks `fetch` / `XHR` / `sendBeacon`, extracts blob fields and activity names | Tampermonkey | Your browsing | POST requests to `127.0.0.1:8766/ingest` |
| `reflex.py` | Six-section statistical mirror-portrait renderer | A terminal (Python 3.9+) | NDJSON (one blob per line) | One `report.html` |
| `generate_sample.py` | Deterministic synthetic session generator | A terminal | Seed + event count | Synthetic NDJSON |

Everything is stdlib only on the Python side. No `pip install`. No virtualenv.

---

## What it reveals

On the included synthetic sample (`Reflex/sample_session.ndjson`, 800 events, seed 1729), Reflex surfaces:

- Next-surface prediction **89.3% accurate** versus a 35.8% baseline &rarr; **2.49&times; lift**
- `msg` content is **2.40&times; more likely** to appear in the five events immediately before you take an action than baseline expects
- Peak activity at **14:00 UTC**, accounting for **31%** of the session
- A dominant **~45-minute rhythm** in attention oscillation

On your own captures you'll see your numbers, not these. That's the point.

A rendered portrait of the sample lives at [`Reflex/sample_report.html`](Reflex/sample_report.html).

---

<img width="1915" height="834" alt="image" src="https://github.com/user-attachments/assets/e92248aa-ce77-45fd-9a33-4c771e303bcc" />


## Quick start (five minutes)

You need Python (3.9+), a Chromium-family browser, and the free [Tampermonkey](https://www.tampermonkey.net/) extension.

### 1 &mdash; Start the relay with a capture file

```bash
cd Session_Cosmos
python cosmos_relay.py --log session.ndjson
```

You'll see a neon banner and three confirmation lines:

```
✎ NDJSON capture enabled → session.ndjson  (appending; 0 existing line(s))
WebSocket server listening on 127.0.0.1:8765
HTTP ingest listening on 127.0.0.1:8766
Ready. Open session_cosmos.html and click CONNECT.
```

Sanity check from any other terminal:

```bash
curl http://127.0.0.1:8766/health
# {"status":"ok","clients":0,"version":"1.2","ports":{"ws":8765,"http":8766},
#  "log":{"enabled":true,"path":"session.ndjson","written":0}}
```

### 2 &mdash; Open the visualizer

Double-click `Session_Cosmos/session_cosmos.html`. It opens in your default browser with a pre-built synthetic cosmos so the scene isn't empty on first launch.

On the right panel, click the **STREAM** tab, confirm the URL reads `ws://localhost:8765`, click **CONNECT**. The status pip should go cyan and read `STREAM LIVE`. The relay terminal will log the new client.

### 3 &mdash; Install the userscript

1. Click the Tampermonkey toolbar icon &rarr; **Create a new script**.
2. Delete the template. Paste the full contents of `Session_Cosmos/facebook-interceptor.user_1.js` (v1.1 &mdash; the canonical one; `.user.js` is the legacy v1.0 blob-only version).
3. Save with Ctrl/Cmd+S. Make sure it shows as enabled in the Tampermonkey dashboard.

Visit [facebook.com](https://www.facebook.com). A neon HUD appears top-right &mdash; that's the interceptor. Scroll. Click between Home, Profile, Messenger, Marketplace. You'll see `captured` / `streamed` counters climb and the `last activity` line update with friendly names like "Scrolling feed" or "Viewing a profile".

Switch back to the Session Cosmos tab &mdash; new nodes spawn in real time. The relay terminal logs every blob. `session.ndjson` grows on disk.

### 4 &mdash; Run Reflex on what you captured

```bash
cd ../Reflex
python reflex.py ../Session_Cosmos/session.ndjson -o my_report.html --title "my session"
open my_report.html      # macOS
xdg-open my_report.html  # Linux
start my_report.html     # Windows
```

If you haven't captured anything yet, use the bundled 800-event synthetic sample:

```bash
python reflex.py sample_session.ndjson -o report.html
```

---

<img width="1902" height="908" alt="image" src="https://github.com/user-attachments/assets/43a229da-9efb-4f8d-9cf2-7bebffd57efe" />


## Architecture

```
┌────────────────┐       ┌──────────────┐        ┌─────────────────┐
│  Facebook tab  │       │ cosmos_relay │        │ session_cosmos  │
│ (Tampermonkey  │──POST─▶│    .py       │──WS──▶│    .html        │
│  interceptor)  │       │              │        │  (3D viewer)    │
└────────────────┘       └──────┬───────┘        └─────────────────┘
   hooks fetch / XHR /          │ optional
   sendBeacon, extracts         │ --log
   blob fields +                ▼
   fb_api_req_friendly_name  session.ndjson
                                │
                                ▼
                        ┌───────────────┐        ┌─────────────────┐
                        │   reflex.py   │──────▶│   report.html    │
                        │ (offline, 6   │        │ (one HTML file)  │
                        │  analyses)    │        │                  │
                        └───────────────┘        └─────────────────┘
```

The two tools are decoupled through a single file format: NDJSON, one captured blob per line. You can run Session Cosmos without ever touching Reflex, and you can run Reflex on anyone's NDJSON (including your own from months ago) without the relay needing to be up.

---

<img width="823" height="477" alt="image" src="https://github.com/user-attachments/assets/7516a112-4b2a-4aad-9607-fea8083e37aa" />


## Session Cosmos in depth

### What the interceptor captures

The v1.1 userscript extracts two kinds of fields from every outgoing `fetch` / `XMLHttpRequest` / `navigator.sendBeacon`:

**Blob fields** (the telemetry envelope):

```
__a   __aaid   __ccg   __comet_req   __crn   __hs   __hsi
__req __rev    __s     __spin_b      __spin_r __spin_t __user
dpr   fb_dtsg  jazoest lsd           ph
```

**Activity-context fields** (what you're actually doing):

```
fb_api_req_friendly_name   # e.g. "CometUFIFeedbackLikeMutation"
fb_api_caller_class
doc_id                     # persisted GraphQL query id
server_timestamps
```

Requests without at least `__req` and `__crn` are ignored. Identical routes are deduped within a short window so the relay isn't spammed by autoscroll bursts.

### The relay (`cosmos_relay.py`, v1.2)

One file. Stdlib only. Two servers on two ports:

- `127.0.0.1:8765` &mdash; WebSocket, broadcasts every incoming blob to all connected clients. Server-initiated pings every 20 s keep NAT / proxies / firewalls happy.
- `127.0.0.1:8766` &mdash; HTTP, accepts `POST /ingest` from the userscript, `GET /health` for diagnostics.

Passing `--log PATH`:

- Appends every blob as one JSON line (NDJSON). Survives restarts cleanly &mdash; re-running with the same path picks up where you left off, and the startup banner prints the existing line count.
- Flushes per-line, so `kill -9` never drops blobs.
- Parent directories auto-created (`--log logs/april/session.ndjson` just works).
- `/health` additionally returns `{"log": {"enabled": true, "path": "...", "written": N}}`.

### The visualizer (`session_cosmos.html`)

Single self-contained HTML file. Three.js inlined. No build. No npm. Double-click and you're in.

**Controls**

| Input | Action |
|---|---|
| Drag | Orbit the cosmos |
| Scroll | Zoom |
| Click a node | Full telemetry popover |
| `ORBIT` / `TOPDOWN` / `REPLAY` | Camera modes (top-right) |
| `REPLAY` scrubber | Fly along your session chronologically |
| `MANUAL` tab | Paste one or many blobs from clipboard (separate with blank lines or `===`) |
| `LIVE PASTE` tab | Auto-ingest on pause |
| `STREAM` tab | Connect to the relay for real-time streaming |

**Encoding legend**

| Visual | Data |
|---|---|
| Node altitude | Facebook surface (HOME / PROFILE / MESSENGER / MARKETPLACE / etc.) |
| Horizontal position | Time / request sequence |
| Node size | Big = real anchored data; small = reconstructed |
| Node color | Surface colour (cyan HOME, pink PROFILE, amber MESSENGER, ...) |
| Ringed node | Real anchored blob |
| Edge colour | Connection quality at that moment (GOOD / POOR / BAD) |
| Pink dashed vertical line | Bundle revision deploy detected mid-session |
| Pulsing frontmost node | The most recent / "now" event |

---

## Reflex in depth

One Python file, ~1000 lines, six analyses, pure SVG output. Each analysis is a pure function over a list of `Event` objects; each is paired with a `render_*()` function that emits an SVG string; the HTML template stitches them together with a Blade Runner observatory aesthetic.

To add your own analysis: write `analysis_*()` &rarr; `render_*()` &rarr; add a `section(...)` call inside `build_report()`.

### The six panels

| # | Panel | What it reveals |
|---|---|---|
| 01 | **Action&ndash;Response Envelope** | The feed's density curve around the moments you tap. Averaged across every action you took. |
| 02 | **Surface Transition Matrix** | Your habitual paths through the app, as probabilities. Where muscle memory takes you when you don't think. |
| 03 | **Session Rhythm** | Minute-by-minute activity density with burst detection and autocorrelation. Your session's pulse and period. |
| 04 | **Hook Moments** | Which content categories appear more often than baseline in the five events *before* you take an action. Empirically, what hooks you. |
| 05 | **Diurnal Portrait** | A 24-hour polar signature. The hours you belong to yourself, and the hours you belong to the feed. |
| 06 | **Prediction Engine** | 80/20 train-test Markov model. Accuracy vs. random baseline, plus a crystal ball showing the most likely next move from wherever your session ended. |

### Activity decoder

Reflex classifies each request into one of six categories &mdash; `view`, `act`, `msg`, `compose`, `search`, `nav` &mdash; using ~40 regex patterns against `fb_api_req_friendly_name`. Unmatched names fall through to a generic `Performing action` (mutations) or `Loading data` (queries). Extending the decoder is one-line-per-pattern: edit `ACTIVITY_PATTERNS` in [`Reflex/reflex.py`](Reflex/reflex.py).

### CLI

```bash
python reflex.py INPUT.ndjson [-o OUTPUT.html] [--title "TEXT"]
```

Generate your own synthetic session:

```bash
python generate_sample.py --events 2000 --seed 42 -o my_sample.ndjson
```

---

## Repository layout

```
Mark Interceptor/
├── README.md                               # this file
│
├── Session_Cosmos/                         # live capture + 3D viewer
│   ├── cosmos_relay.py                     # WebSocket + HTTP + NDJSON recorder
│   ├── session_cosmos.html                 # standalone 3D visualizer
│   ├── facebook-interceptor.user_1.js      # userscript v1.1 (canonical)
│   ├── facebook-interceptor.user.js        # userscript v1.0 (legacy)
│   └── README.md                           # component-level docs
│
└── Reflex/                                 # offline mirror analysis
    ├── reflex.py                           # main tool, six analyses
    ├── generate_sample.py                  # deterministic synthetic sessions
    ├── sample_session.ndjson               # 800-event sample (seed 1729)
    ├── sample_report.html                  # pre-rendered portrait of the sample
    ├── hero.png                            # report header image
    ├── section_*.png                       # gallery imagery
    └── README.md                           # component-level docs
```

The two component folders are deliberately kept independent &mdash; each has its own README and can be split into its own repository later without surgery. They communicate only through NDJSON on disk.

---

## Privacy and ethics

This is a **self-research tool**. It operates exclusively on data you captured from your own browser, while you were logged into your own account, on a machine you control.

**Design guarantees**

- The relay binds to `127.0.0.1`. No external network can reach it.
- The userscript sends blobs *only* to the local relay. It does not phone home.
- The visualizer hides sensitive tokens (`fb_dtsg`, `lsd`, `jazoest`) from the detail view by default to prevent accidental screen-recording leaks.
- Reflex runs entirely in memory and writes exactly one local HTML file.

**What the tools do NOT do**

- They do not connect to Facebook or any third-party service.
- They do not bypass authentication, rate limits, or platform protections.
- They do not collect data from anyone other than the user running them.
- They do not impersonate the user, automate their account, or interact with the feed in any way.
- They do not try to manipulate, reverse-engineer, or game the ranking algorithm.

**The ethical moat: category space, not identity space**

These tools analyse *patterns in you* &mdash; your rhythms, your habits, what hooks you &mdash; not identities of anyone else embedded in your network. If you extend them, keep it that way. "You liked something of category `act`" is self-research. "You liked this specific post by this specific person" is not. Don't cross that line; don't let this tool help anyone else cross it either.

**Before you share**

Captured blobs contain session-scoped anti-CSRF tokens (`fb_dtsg`, `lsd`, `jazoest`). Treat NDJSON files, screenshots of the telemetry panel, and raw exports as you would a browser cookie: don't post them publicly, don't ship them in bug reports unredacted.

This places Mark Interceptor in the tradition of algorithmic-transparency projects like [AI Forensics](https://aiforensics.org), Mozilla's [YouTube Regrets](https://foundation.mozilla.org/en/youtube/), and [The Markup's Citizen Browser](https://themarkup.org/series/citizen-browser).

---

## Troubleshooting

**Visualizer says `CONNECTION ERROR` or `RELAY UNREACHABLE`.**
Is the relay running? Check its terminal. Hit `http://127.0.0.1:8766/health` in a browser &mdash; you should get a JSON blob. If not, something is blocking the port or the relay didn't start. See Platform notes below.

**Something else is squatting on the ports.**

```bash
# macOS / Linux
lsof -i :8765 -i :8766

# Windows
netstat -ano | findstr "8765 8766"
```

Stop whatever holds the port, or change `WS_PORT` / `HTTP_PORT` in `cosmos_relay.py` (and match them in the userscript's `RELAY_URL` and the visualizer's STREAM tab).

**HUD appears but `captured` stays at 0.**
The page may not have generated telemetry yet. Switching between Home and Profile is a guaranteed trigger. If it stays at zero, open devtools and look for `[SESSION COSMOS] Interceptor armed` in the console &mdash; that confirms the script loaded.

**CORS error in the browser console.**
You're probably POSTing to `localhost` instead of `127.0.0.1` &mdash; some browsers treat them as different origins. The shipped userscript uses `127.0.0.1`; if you edited it, match the relay.

**Tampermonkey says `GM_xmlhttpRequest not allowed`.**
The userscript's header has `@grant GM_xmlhttpRequest` and `@connect 127.0.0.1`. If those are missing (e.g. you pasted only the function body), Tampermonkey won't authorise the cross-origin POST. Paste the whole file including the `==UserScript==` banner.

**Reflex prints `parsed 0 events`.**
The input file isn't NDJSON, or every line failed to parse as JSON. Tail the file and make sure each line is a standalone JSON object.

---

## Platform notes

### Windows

Python's default stdout encoding on Windows is `cp1252`, which cannot print the Unicode box-drawing characters used in the relay banner. You'll see:

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 7-71
```

Fix it by running Python in UTF-8 mode (pick one):

```bash
py -X utf8 cosmos_relay.py --log session.ndjson
```

or set the environment variable once:

```bash
set PYTHONIOENCODING=utf-8
```

or permanently (PowerShell):

```powershell
[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'User')
```

Windows Terminal and recent PowerShell handle the ANSI colour codes correctly. Older `cmd.exe` strips them.

### macOS / Linux

No special setup. `python3` or `python` &mdash; whichever is on your `PATH` and &ge; 3.9 for Reflex, &ge; 3.7 for the relay.

### Browsers

The visualizer is built against evergreen Chrome / Edge / Firefox / Safari. The userscript is tested on Tampermonkey; Violentmonkey should work identically.

---

## Roadmap

Shipped

- `--log` flag on the relay writes captures directly to NDJSON _(relay v1.2)_
- Activity-context capture (`fb_api_req_friendly_name`) _(userscript v1.1)_
- Startup banner reports existing-line count for append-mode captures
- `/health` endpoint reports log status

Likely next

- Cross-session comparison in Reflex (two sessions &rarr; diff portrait; "you on Tuesday vs you on Saturday")
- Pattern-discovery tool: scan an NDJSON, list unmatched `friendly_name`s by frequency to grow the decoder
- Session segmentation (detect natural boundaries in `__rev` / `__hsi` jumps rather than treating a multi-day NDJSON as one run)
- Predictive validation on live data (train on week 1, predict week 2, measure held-out accuracy)
- Per-surface breakdown of the Action&ndash;Response Envelope
- Export analyses as JSON for further processing
- PDF export
- Local-timezone diurnal portrait (currently UTC)
- Real-time Reflex: web viewer that slurps the WS stream live

Unclaimed adjacent tool (a *third* piece, not planned for this repo)

Session Cosmos **captures**, Reflex **analyses**. The unclaimed niche is **intervention** &mdash; a tool that, after you see your portrait, lets you set boundaries with yourself: block hook-moment patterns, mute your highest-lift categories, circuit-break your burst cadence. Candidate names: *Embargo*, *Parley*, *The Blinders*. If you build it, link back.

---

## Contributing

Issues and PRs welcome. Small, focused changes over sweeping refactors. For new Reflex analyses, follow the `analysis_*()` &rarr; `render_*()` &rarr; `section(...)` pattern already in the file. For new decoder patterns, append to `ACTIVITY_PATTERNS` with a comment showing an example `friendly_name`. For relay changes, preserve stdlib-only and keep the startup output scannable.

If you capture something interesting on real data &mdash; unusual blob shapes, operation names that fall through the decoder, a diurnal portrait that surprises you &mdash; open an issue. The decoder's regex list was written from memory and is deliberately incomplete; real captures are how it grows.

---

## License

MIT. Do what you want. Watch the watcher.

---

## Credits

Built with [Claude](https://claude.ai). Aesthetic borrowed from late-night synthwave and the covers of old cyberpunk paperbacks.

## Final Note
Fuck off Mark
