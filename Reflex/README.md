# REFLEX

> **Mirror analysis for Session Cosmos captures.**
> _The algorithm is watching you. Watch it watching you._

![Reflex sample report header](docs/hero.png)

---

Reflex is a self-contained Python tool that reads a newline-delimited JSON file of Facebook/Meta request telemetry — the kind captured by the [Session Cosmos](https://github.com/you/session-cosmos) userscript — and renders a single HTML portrait revealing the feedback loop between **you** and the **ranking algorithm**.

It runs entirely offline. It never touches Facebook. It only analyzes metadata you already captured from your own browser session.

The output is one HTML file you can open, share, screenshot, or archive.

## What it shows

Six analyses, all computed from request-sequence metadata alone — no content, no API calls:

| # | Analysis | What it reveals |
|---|----------|-----------------|
| 01 | **Action–Response Envelope** | The feed's density curve around the moments you tap. What the algorithm served you, averaged across every action. |
| 02 | **Surface Transition Matrix** | Your habitual paths through the app, as probabilities. Where muscle memory takes you when you don't think. |
| 03 | **Session Rhythm** | Minute-by-minute activity density with burst detection and autocorrelation. Your session's pulse and period. |
| 04 | **Hook Moments** | Which content categories appear more often than baseline in the 5 events before you take an action. Empirically, what hooks you. |
| 05 | **Diurnal Portrait** | Your 24-hour polar signature. The hours you belong to yourself, and the hours you belong to the feed. |
| 06 | **Prediction Engine** | 80/20 train-test Markov model. Accuracy vs baseline, plus a crystal ball showing the most likely next move from wherever your session ended. |

## Sample output

On the included synthetic sample (`sample_session.ndjson`, 800 events, seed 1729), Reflex finds:

- Next-surface prediction **89.3% accurate** vs 35.8% baseline → **2.49× lift**
- `msg` content is **2.40× more likely** to appear in the 5 events before an action than baseline
- Peak activity at **14:00 UTC**, accounting for 31% of the session
- A dominant **~45 minute rhythm** in attention oscillation

See `docs/sample_report.html` for the full rendered portrait.

## Install + run

**Zero dependencies.** Python 3.9+ stdlib only.

```bash
git clone https://github.com/you/reflex && cd reflex

# Try it on the included sample
python reflex.py sample_session.ndjson -o report.html
open report.html   # or xdg-open / start

# Generate your own sample with different parameters
python generate_sample.py --events 2000 --seed 42 -o my_sample.ndjson
python reflex.py my_sample.ndjson -o my_report.html

# On real data from Session Cosmos (one JSON blob per line):
python reflex.py my_capture.ndjson -o my_report.html --title "my monday evening"
```

## Capturing your own session

Reflex reads NDJSON (newline-delimited JSON) where each line is one captured Facebook request blob. The easiest way to produce this is with [Session Cosmos](https://github.com/you/session-cosmos) — install the Tampermonkey userscript, run the relay, and log the stream:

```bash
# Session Cosmos relay, plus tee to a capture file
python cosmos_relay.py | tee >(grep '^▸ BLOB' > /dev/null)   # relay logs only
# Or modify the relay to write broadcasts to a file directly.
```

A simpler path is to let Session Cosmos run and periodically `curl -s http://127.0.0.1:8766/health` for sanity; Reflex can work on any NDJSON you produce by tapping the stream.

_Future work: a `--log <path>` flag on the relay itself. PRs welcome._

## Scope and ethics

Reflex is a **self-research tool**. It operates only on data you captured from your own browser, while you were logged into your own account, on a machine you control.

It does NOT:

- connect to Facebook or any other service
- bypass authentication, protections, or rate limits
- collect third-party data
- impersonate or automate the user
- attempt to manipulate or game the ranking algorithm

It DOES:

- parse operation-sequence metadata from your local capture
- run statistical analyses entirely in memory
- write one local HTML file

This framing places Reflex in the tradition of algorithmic-transparency projects like [AI Forensics](https://aiforensics.org), Mozilla's [YouTube Regrets](https://foundation.mozilla.org/en/youtube/), and [The Markup's Citizen Browser](https://themarkup.org/series/citizen-browser). Inspect your own shadow.

## Architecture

One file, six analyses, pure SVG output.

```
reflex/
├── reflex.py                   # ~1000 lines — main tool
├── generate_sample.py          # deterministic synthetic session generator
├── sample_session.ndjson       # 800 events (seed 1729)
├── docs/
│   └── sample_report.html      # rendered output
└── README.md
```

Each analysis is a pure function that takes a list of `Event` objects and returns a dict. Each dict is handed to a corresponding `render_*` function that returns an SVG string. The HTML template stitches them together with the Blade Runner observatory aesthetic.

To add a new analysis: write `analysis_*()` → `render_*()` → add a `section(...)` call in `build_report()`.

## Gallery

### Surface transitions (you on autopilot)

![Transition matrix](docs/section_transitions.png)

### Hook moments (what actually gets you to tap)

![Hook moments](docs/section_hooks.png)

### Diurnal portrait (when you belong to the feed)

![Diurnal wheel](docs/section_diurnal.png)

### Prediction engine (the mirror predicts)

![Predictions](docs/section_predictions.png)

## Roadmap

- [ ] `--log` flag on Session Cosmos relay to write captures directly to NDJSON
- [ ] Cross-session comparison (two sessions → diff portrait)
- [ ] Per-surface breakdown of the Action-Response Envelope
- [ ] Export analyses as JSON for further processing
- [ ] Export as PDF
- [ ] Local timezone support for the diurnal portrait (currently UTC only)
- [ ] Web viewer that slurps a stream live (real-time Reflex)

## License

MIT. Do what you want. Watch the watcher.

## Credits

Built with [Claude](https://claude.ai) as part of the Session Cosmos project family. Aesthetic borrowed from late-night synthwave and the covers of old cyberpunk paperbacks.
