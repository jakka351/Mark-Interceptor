# $\color{#00ffd1}{\textsf{M A R K · I N T E R C E P T O R}}$

> $\color{#ff4fd8}{\textsf{Watching the reflection of Facebook watching us.}}$
> $\color{#7ad7ff}{\textsf{A way to look inside of the algorithm.}}$ **$\color{#fff275}{\textsf{v0.2.0 — SUPERCHARGED}}$**

```diff
+ ╔════════════════════════════════════════════════════════════════╗
+ ║  Capture your own Facebook session telemetry.                  ║
+ ║  Watch it render as a 3D cosmos.                               ║
+ ║  Let the mirror tell you who you are when the algorithm        ║
+ ║  is watching.                                                  ║
+ ╚════════════════════════════════════════════════════════════════╝
```

A **two-part, localhost-only toolkit for algorithmic self-research:**

- $\color{#00ffd1}{\textsf{SESSION·COSMOS}}$ — captures the hidden telemetry fields Facebook/Meta attaches to every request, and renders them live as a navigable 3D space you can fly through.
- $\color{#ff4fd8}{\textsf{REFLEX}}$ — reads the captured stream back offline and produces a single self-contained HTML portrait of the feedback loop between *you* and the ranking algorithm. **13 analysis panels** covering surface transitions, hook moments with permutation-tested significance, hover→action conversion, ad dose-response, time-to-action survival curves, and the rarely-seen *self-surveillance* meta-layer — Facebook's own telemetry of you, captured from inside your browser.

<br/>
<br/>
<sup>

**$\color{#00ffd1}{\textsf{Pure Python stdlib backend.}}$ $\color{#ff4fd8}{\textsf{Zero build step frontend.}}$ $\color{#fff275}{\textsf{Nothing leaves your machine.}}$ $\color{#9d7bff}{\textsf{No calls home.}}$**

</sup>

<img width="929" height="381" alt="image" src="https://github.com/user-attachments/assets/cb280570-c38e-45a4-bc46-5c2266c97283" />

```console
▓▒░ ENTITY FINGERPRINT ░▒▓
  captures : localhost only
  exfil    : none
  decoder  : 118 patterns / 12 categories / 97.9% coverage on real data
  stats    : MAD bursts · Welch periodogram · Laplace Markov · permutation tests
  outputs  : ONE html file · no JavaScript framework · opens with a double-click
```

---

## $\color{#00ffd1}{\textsf{Table of contents}}$

1. [What you get](#what-you-get)
2. [What it reveals](#what-it-reveals)
3. [$\color{#ff4fd8}{\textsf{What data we capture}}$](#what-data-we-capture)  *◀ new in v0.2.0*
4. [$\color{#ff4fd8}{\textsf{The 13 analysis panels}}$](#the-13-analysis-panels)  *◀ new in v0.2.0*
5. [$\color{#ff4fd8}{\textsf{Taxonomy — 12 categories}}$](#taxonomy--12-categories)  *◀ new in v0.2.0*
6. [$\color{#ff4fd8}{\textsf{Statistical rigor}}$](#statistical-rigor)  *◀ new in v0.2.0*
7. [Quick start](#quick-start-five-minutes)
8. [Architecture](#architecture)
9. [Session Cosmos in depth](#session-cosmos-in-depth)
10. [Reflex in depth](#reflex-in-depth)
11. [Repository layout](#repository-layout)
12. [Privacy and ethics](#privacy-and-ethics)
13. [Troubleshooting](#troubleshooting)
14. [Platform notes](#platform-notes)
15. [Roadmap](#roadmap)
16. [Contributing](#contributing)
17. [License](#license)

---

## $\color{#00ffd1}{\textsf{What you get}}$

<img width="1904" height="888" alt="image" src="https://github.com/user-attachments/assets/0b9fbec8-0277-4b44-9a89-8b8a4a2b3af8" />


| Component | What it does | Runs in | Inputs | Outputs |
|---|---|---|---|---|
| `cosmos_relay.py` **v2.0** | WebSocket broadcaster + HTTP ingest + NDJSON recorder + multi-kind event routing + monotonic `__relay_seq` stamp | A terminal (Python 3.7+) | HTTP POSTs from the userscript | Live WS stream + `session.ndjson` |
| `session_cosmos.html` | 3D visualizer (Three.js, single file, no build step) | Your browser | WS stream from the relay | A flyable cosmos |
| `facebook-interceptor.user_1.js` | Userscript v1.1 — hooks `fetch` / `XHR` / `sendBeacon`, extracts blob fields and activity names | Tampermonkey | Your browsing | POST requests to `127.0.0.1:8766/ingest` |
| `facebook-interceptor.user_2.js` **v2.0** | Supercharged — adds response latency, `localStorage` buffer (survives relay restarts), scroll-velocity sampler, `visibilitychange` sensor, per-tab id, `@match` for Instagram + Threads | Tampermonkey | Your browsing | Request + input + visibility events to relay |
| `reflex.py` **v0.2.0** | **Thirteen**-section mirror-portrait renderer · expanded 118-pattern decoder · permutation-tested hooks · cross-session diff · SQLite longitudinal store | A terminal (Python 3.9+) | NDJSON (one blob per line) | One `report.html` |
| `reflex_discover.py` **new** | Char-trigram Jaccard clustering of unmatched friendly_names → auto-suggests regexes + categories + icons | A terminal | NDJSON file(s) | Python snippet ready to paste into ACTIVITY_PATTERNS |
| `reflex_live.html` **new** | Real-time portrait: rolling-window analyses re-computed every 750 ms from the live WebSocket stream | Your browser | WS stream from the relay | Live mirror in the browser |
| `generate_sample.py` | Deterministic synthetic session generator | A terminal | Seed + event count | Synthetic NDJSON |

Everything is stdlib only on the Python side. $\color{#ff4fd8}{\textsf{No}}$ `pip install`. $\color{#ff4fd8}{\textsf{No}}$ virtualenv. $\color{#ff4fd8}{\textsf{No}}$ external network.

---

## $\color{#00ffd1}{\textsf{What it reveals}}$

On the included synthetic sample (`Reflex/sample_session.ndjson`, 800 events, seed 1729), Reflex surfaces:

- Next-surface prediction **89.3% accurate** versus a 35.8% baseline &rarr; **2.49&times; lift**
- `msg` content is **2.40&times; more likely** to appear in the five events immediately before you take an action than baseline expects
- Peak activity at **14:00 UTC**, accounting for **31%** of the session
- A dominant **~45-minute rhythm** in attention oscillation

On your own captures you'll see your numbers, not these. That's the point.

```diff
+ ┌─── v0.2.0 DEMONSTRATED ON REAL DATA ─────────────────────────┐
+ │  1,979 events · 10 session segments · 4 bundle revisions     │
+ │  DECODER COVERAGE .......... 33.0% → 97.9%                   │
+ │  MSG hook ............ 2.46× · p = 0.002 ***                 │
+ │  SEARCH hook ......... 2.33× · p = 0.002 ***                 │
+ │  HOVER conversion .... 1.38× baseline within ~4 events       │
+ │  PREDICTION (5-fold CV) ........ 92.5% ± low-variance        │
+ │  FB self-surveillance captured ........ 76 events            │
+ │  PRESENCE pings captured ............. 148 events            │
+ │  FREE A/B tests found inside capture ..... 3 rev boundaries  │
+ └──────────────────────────────────────────────────────────────┘
```

A rendered portrait of the sample lives at [`Reflex/sample_report.html`](Reflex/sample_report.html).
The $\color{#00ffd1}{\textsf{live-updating viewer}}$ lives at [`Reflex/reflex_live.html`](Reflex/reflex_live.html).

---

<img width="1915" height="834" alt="image" src="https://github.com/user-attachments/assets/e92248aa-ce77-45fd-9a33-4c771e303bcc" />


## $\color{#ff4fd8}{\textsf{What data we capture}}$

Every entry in the NDJSON log is one captured request, sensor event, or visibility transition. The interceptor extracts these exact fields — nothing else leaves the page context, nothing you'd call "content" or "personal data beyond the envelope" is touched.

### $\color{#7ad7ff}{\textsf{Structural fields}}$ (the telemetry envelope)

```diff
+ ┌─────────────────┬──────────────────────────────────────────────────┬──────────────────────────┐
+ │ FIELD           │ WHAT IT IS                                       │ USED IN                  │
+ ├─────────────────┼──────────────────────────────────────────────────┼──────────────────────────┤
+ │ __req           │ Monotonic client-side request counter (base-36)  │ Seq ordering, dedup      │
+ │ __crn           │ Comet route — which Facebook surface             │ 02 transitions · 06 pred │
+ │ __rev           │ Bundle revision — which code shipped to you      │ 09 rev boundaries        │
+ │ __spin_t        │ Server-side seconds-epoch timestamp              │ Every time-based panel   │
+ │ __spin_b        │ Bundle branch (trunk, etc.)                      │ 09 rev context           │
+ │ __spin_r        │ Spin revision                                    │ 09 rev context           │
+ │ __hs / __hsi    │ Handshake / hash                                 │ Session-integrity signal │
+ │ __ccg           │ Connection-quality code (GOOD/MODERATE/POOR/BAD) │ CCG overlay on edges     │
+ │ __comet_req     │ Comet internal request sub-seq                   │ Dedup                    │
+ │ __url_path      │ Which endpoint (/api/graphql/, /ajax/…)          │ Fallback classifier      │
+ │ __tab_id (v2)   │ Random per-browser-tab id                        │ Cross-tab dedup          │
+ │ __latency_ms    │ fetch/XHR response latency (v2)                  │ 12 anomaly scoring       │
+ │ __response_size │ Response bytes (v2, best-effort)                 │ Anomaly + size analysis  │
+ │ __relay_seq (v2)│ Monotonic relay-side broadcast id                │ Drop detection           │
+ └─────────────────┴──────────────────────────────────────────────────┴──────────────────────────┘
```

### $\color{#7ad7ff}{\textsf{Activity-context fields}}$ (the semantic layer)

```diff
+ ┌──────────────────────────────────┬─────────────────────────────────────────────────────────────┐
+ │ FIELD                            │ PURPOSE                                                     │
+ ├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
+ │ fb_api_req_friendly_name         │ Operation name (e.g. CometUFIFeedbackLikeMutation)          │
+ │                                  │ — THE key field: drives category, label, icon               │
+ │ fb_api_caller_class              │ Which caller class issued the request                       │
+ │ doc_id                           │ Persisted GraphQL query id (stable across user sessions,    │
+ │                                  │ churns when FB deploys new bundles)                         │
+ │ server_timestamps                │ If present, indicates FB-tagged timings                     │
+ └──────────────────────────────────┴─────────────────────────────────────────────────────────────┘
```

### $\color{#ff4fd8}{\textsf{What is NEVER captured}}$

$\color{#ff4fd8}{\textsf{NO}}$ post contents · $\color{#ff4fd8}{\textsf{NO}}$ message bodies · $\color{#ff4fd8}{\textsf{NO}}$ target user IDs (other than your own `__user`) · $\color{#ff4fd8}{\textsf{NO}}$ response bodies · $\color{#ff4fd8}{\textsf{NO}}$ photo data · $\color{#ff4fd8}{\textsf{NO}}$ friend/follower graphs · $\color{#ff4fd8}{\textsf{NO}}$ third-party data.

**GraphQL `variables` are captured but hard-capped at 300 chars** to prevent accidental extraction of payload content. The variables are treated as opaque entropy for segmentation, never parsed for identifiers.

### $\color{#7ad7ff}{\textsf{Redacted-at-rest tokens}}$

These are captured in the raw NDJSON because they're bound inside request bodies, but they're **masked from the visualizer's detail view by default** and stripped to a per-install salt when ingested into the longitudinal SQLite store:

```console
fb_dtsg    jazoest    lsd    __user    __s
```

### $\color{#7ad7ff}{\textsf{Sensor events}}$ (userscript v2.0 only)

In addition to request blobs, the v2.0 userscript emits low-rate behavioral sensors as separate events with `__kind != 'request'`. These are useful for survival analysis and for correlating activity with physical attention.

```diff
+ ┌───────────────────┬────────────────────────────────────────────────────────────────────────┐
+ │ __kind=input      │ Scroll-velocity sampler. Emits when scroll delta > 10px in a 1s window.│
+ │                   │ Fields: __delta_px, __velocity_px_per_s, __ts_wall                     │
+ ├───────────────────┼────────────────────────────────────────────────────────────────────────┤
+ │ __kind=visibility │ Tab gain/loss of focus. Fields: __event ∈ {visible, hidden}            │
+ │                   │ Tells you when the session actually ended (vs just idled).             │
+ └───────────────────┴────────────────────────────────────────────────────────────────────────┘
```

---

## $\color{#ff4fd8}{\textsf{The 13 analysis panels}}$

Every Reflex HTML report is a single self-contained file with 13 sections. Each section does one thing end-to-end: an analysis function over your events returns a dict, a renderer turns that dict into an SVG, and an auto-generated *OBSERVATION* box translates the numbers into plain English. The descriptions below are verbatim from the rendered report.

```diff
+ ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
+ │ #   PANEL                              WHAT IT SHOWS                                        │
+ ├─────────────────────────────────────────────────────────────────────────────────────────────┤
+ │ 01  ACTION — RESPONSE ENVELOPE         The algorithm's reply around each tap.               │
+ │ 02  SURFACE TRANSITION MATRIX          Muscle-memory routes between Facebook surfaces.      │
+ │ 03  SESSION RHYTHM                     Activity cadence + MAD-based burst markers.          │
+ │ 04  HOOK MOMENTS                       Categories over-represented before you act (p<0.01). │
+ │ 05  DIURNAL PORTRAIT                   24-hour clock, colored by category.                  │
+ │ 06  PREDICTION ENGINE                  Markov crystal ball + 5-fold time-series CV.         │
+ │ 07  HOVER — ACTION CONVERSION          Does a mouseover predict the click? (new in 0.2)     │
+ │ 08  AD DOSE — RESPONSE                 Cumulative action prob after each ad. (new)          │
+ │ 09  REVISION BOUNDARIES                Facebook's mid-session deploys as free A/B tests.(new)│
+ │ 10  TIME-TO-ACTION SURVIVAL            Kaplan-Meier of view → action. (new)                 │
+ │ 11  SELF-SURVEILLANCE META-LAYER       FB's own telemetry of you. (new)                     │
+ │ 12  ANOMALY SURFACING                  Top-10 unusual moments in the session. (new)         │
+ │ 13  DECODER SELF-DIAGNOSTIC            How much of your capture Reflex actually understood. │
+ └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### $\color{#7ad7ff}{\textsf{Panel details}}$

**$\color{#00ffd1}{\textsf{01 · ACTION — RESPONSE ENVELOPE}}$**
For every action you took — a like, a comment, a message, a share — Reflex averages the activity density in the 30 requests before and 30 requests after the moment you tapped. The shape of the resulting curve is the algorithm's reply, averaged into visibility. A spike on the right means the system reacted. A flat line means it didn't — or at least not in a way your own requests could see.

**$\color{#00ffd1}{\textsf{02 · SURFACE TRANSITION MATRIX}}$**
The probability that going to any surface *next* given your current surface. Rows are your current location, columns are where you go next. A strong diagonal means you tend to stay where you are — deep scrolling. Bright off-diagonal cells reveal your habitual paths: the routes your attention takes without you ever consciously choosing.

**$\color{#00ffd1}{\textsf{03 · SESSION RHYTHM}}$**
Activity density over time, bucketed by minute, stacked by category. Pink dots mark *burst moments* — buckets where activity exceeds the session's **MAD-based threshold** (modified z-score > 3.5, robust to sparse sessions). The dominant period is recovered via a **Welch periodogram**, not a greedy local-max search. System categories (`presence`, `self_surv`, `nav`) are rendered faintly so they don't drown out your own behavior.

**$\color{#00ffd1}{\textsf{04 · HOOK MOMENTS}}$**
For each action you took, Reflex looks at the 5 events immediately before and measures which categories appear more often than their session-wide baseline. Lift values above 1.0× mean that category disproportionately precedes your taps — it's what gets you to act. **v0.2.0 adds a permutation test** (500 shuffles) and prints p-values with `*` `**` `***` significance marks.

**$\color{#00ffd1}{\textsf{05 · DIURNAL PORTRAIT}}$**
Your activity wrapped around a 24-hour clock, with each hour's petals colored by activity category. Length of a petal = total events in that hour. This is your temporal signature: the hours you belong to yourself, and the hours you belong to the feed.

**$\color{#00ffd1}{\textsf{06 · PREDICTION ENGINE}}$**
Reflex splits your session 80/20, trains a **Laplace-smoothed Markov model** on the earlier chunk, and predicts each next event in the later chunk. The **time-series k-fold CV** underneath (5 folds over temporal segments) catches distribution shift a single 80/20 split misses. The crystal ball applies the fully-trained model to your *very last* event: if you kept going right now, what would you probably do?

**$\color{#ff4fd8}{\textsf{07 · HOVER — ACTION CONVERSION}}$** *(new in v0.2.0)*
A mouse hover fires a Hovercard request *before any click*. This panel measures P(action within 10 events | hover at 0) against a random-event baseline. High lift means your hovers are fire-ahead signals — the algorithm, and Reflex, could predict your taps one intention ahead of them. Hover is the proto-commitment; the hand has decided before the click.

**$\color{#ff4fd8}{\textsf{08 · AD DOSE — RESPONSE}}$** *(new in v0.2.0)*
Every `InstreamAds` / `AdsHalo` pre-fetch marks an ad reaching your viewport. This panel plots P(action at offset k | ad at 0) as a **Kaplan-Meier-style cumulative**, against a random-event baseline. The gap between the curves is the measurable behavioral effect of ad exposure, *on you*, with no API access, no survey, no panel — just your own request stream.

**$\color{#ff4fd8}{\textsf{09 · REVISION BOUNDARIES — FREE A/B TESTS}}$** *(new in v0.2.0)*
A `__rev` change mid-session is Facebook shipping new code to you mid-scroll. Reflex catches each boundary, compares the 50 events before and after (category mix, request rate), and shows the delta. Over days or weeks, these are the **richest natural experiments available to anyone who isn't at Meta**.

**$\color{#ff4fd8}{\textsf{10 · TIME-TO-ACTION SURVIVAL}}$** *(new in v0.2.0)*
**Kaplan-Meier-style survival curve**: at each viewing event, the clock starts. P(you haven't acted yet) plotted against elapsed seconds. A sharp early drop = you're quick to engage. A long flat tail = you graze, you don't tap.

**$\color{#ff4fd8}{\textsf{11 · SELF-SURVEILLANCE META-LAYER}}$** *(new in v0.2.0)*
Facebook instruments itself too. `FBScreenTimeLogger_syncMutation`, `TimeLimitsEnforcementQuery`, `RecordProductUsageMutation`, `UnifiedVideoSeenStateMutation` — these fire while you browse. They're Facebook's telemetry of *you*, captured here from inside your own browser. This panel shows the cadence of their sampling — **the ghost's own signal**.

**$\color{#ff4fd8}{\textsf{12 · ANOMALY SURFACING}}$** *(new in v0.2.0)*
Per-event anomaly score built from four features: log-gap to previous event, same-route streak length, category-transition surprisal, and latency deviation. **The top 10 are surfaced — often these are the moments you'd actually remember from the session.**

**$\color{#ff4fd8}{\textsf{13 · DECODER SELF-DIAGNOSTIC}}$** *(new in v0.2.0)*
How much of your capture did Reflex actually understand? The v0.2.0 decoder has 118 patterns covering the full Comet / MAW / BizKit / LSPlatform surface; the ring shows match rate on YOUR data specifically. Top unmatched names are listed — feed them to `reflex_discover.py` and they become new patterns.

### $\color{#7ad7ff}{\textsf{What you see in the report header}}$

Every `report.html` opens with a cyberpunk observatory header:

```diff
+ ╔════════════════════════════════════════════════════════════════╗
+ ║   R E F L E X                                                  ║
+ ║   MIRROR ANALYSIS · SESSION PORTRAIT                           ║
+ ║   generated 2026-04-18 15:29 UTC  ·  span 11:51→11:51 UTC      ║
+ ║   events 1979  ·  surfaces 10                                  ║
+ ╚════════════════════════════════════════════════════════════════╝
```

…followed by a **six-card stat strip**:

| $\color{#00ffd1}{\textsf{total events}}$ | $\color{#00ffd1}{\textsf{actions taken}}$ | $\color{#00ffd1}{\textsf{hover intents}}$ | $\color{#00ffd1}{\textsf{ad impressions}}$ | $\color{#00ffd1}{\textsf{session segments}}$ | $\color{#00ffd1}{\textsf{observed span}}$ |
|---|---|---|---|---|---|
| `1979` | `54` | `131` | `41` | `10` | `8h 53m` |

---

## $\color{#ff4fd8}{\textsf{Taxonomy — 12 categories}}$

Every decoded event lands in exactly one of 12 categories. **v0.2.0 went from 6 → 12** — the new six (`hover`, `ad`, `presence`, `react`, `notif_seen`, `self_surv`) unlock analyses that simply weren't possible before.

### $\color{#00ffd1}{\textsf{User-behavior categories}}$ (the signal)

```diff
+ ┌────────────┬──────────┬────────────────────────────────────────────────────────────────────┐
+ │ CATEGORY   │ COLOR    │ EXAMPLE OPERATION NAMES                                            │
+ ├────────────┼──────────┼────────────────────────────────────────────────────────────────────┤
+ │ view       │ #7ad7ff  │ CometNewsFeedPaginationQuery, HomePageTimelineFeed, StoriesTray    │
+ │ hover      │ #c3f0ff  │ CometHovercardQueryRenderer, UserHovercard, Tooltip content (NEW) │
+ │ react      │ #ff7fbd  │ UFIFeedbackLike, UFIFeedbackReact, UFIRemoveReact (NEW — split    │
+ │            │          │ off from `act` so we can tell likes from actual network actions)   │
+ │ act        │ #ff4fd8  │ SharePost, FriendRequestSend, BlockUser, Save, Hide, Report        │
+ │ msg        │ #ffb347  │ SendMessageMutation, MessengerThread, E2EEBackup, Lightspeed       │
+ │ compose    │ #fff275  │ CommentCreate, PublishPost, StoriesComposer, Composer.Upload       │
+ │ search     │ #9d7bff  │ SearchResults, KeywordsDataSource, MarketplaceSearch               │
+ └────────────┴──────────┴────────────────────────────────────────────────────────────────────┘
```

### $\color{#5a8ca0}{\textsf{System categories}}$ (the substrate)

```diff
+ ┌────────────┬──────────┬────────────────────────────────────────────────────────────────────┐
+ │ CATEGORY   │ COLOR    │ EXAMPLE OPERATION NAMES                                            │
+ ├────────────┼──────────┼────────────────────────────────────────────────────────────────────┤
+ │ nav        │ #66ff99  │ RouteDefinitions, NavBar, PageQuery, WebStorage, Gating            │
+ │ ad         │ #ff9f40  │ useInstreamAdsHaloFetcherQuery, AdsBatch, SponsoredContent  (NEW)  │
+ │ presence   │ #5a8ca0  │ UpdateUserLastActive, PresencePing, HeartbeatMutation  (NEW)       │
+ │ notif_seen │ #b8d4e0  │ NotificationsUpdateSeenState, BadgeCountClear  (NEW)               │
+ │ self_surv  │ #8c5a9a  │ FBScreenTimeLogger_syncMutation, FBYRPTimeLimitsEnforcement,       │
+ │            │          │ RecordProductUsageMutation  (NEW — Facebook's own telemetry)       │
+ └────────────┴──────────┴────────────────────────────────────────────────────────────────────┘
```

**Why split system categories out?** They're noise if you count them as "you," but they're extremely informative when analyzed on their own. `presence` pings reveal when Facebook thinks you're active. `notif_seen` marks the moments of awareness without action. `ad` gives us a dose-response curve. `self_surv` is the ghost's own signal — Facebook's telemetry of you, captured from inside your browser.

---

## $\color{#ff4fd8}{\textsf{Statistical rigor}}$

v0.2.0 replaced a handful of ad-hoc thresholds with principled statistics. Every number in the report now comes with a defensible derivation.

```diff
+ ┌───────────────────┬──────────────────────────────────┬──────────────────────────────────┐
+ │ WHERE             │ OLD (v0.1.x)                     │ NEW (v0.2.0)                     │
+ ├───────────────────┼──────────────────────────────────┼──────────────────────────────────┤
+ │ Burst detection   │ μ + 2σ over nonzero buckets      │ Modified z-score via MAD (k=3.5) │
+ │                   │ — biased on sparse sessions      │ — robust to sparsity + outliers  │
+ ├───────────────────┼──────────────────────────────────┼──────────────────────────────────┤
+ │ Dominant period   │ Greedy first local max of        │ Welch-style periodogram with     │
+ │                   │ autocorr > 0.15                  │ detrending + noise-floor thresh. │
+ ├───────────────────┼──────────────────────────────────┼──────────────────────────────────┤
+ │ Markov smoothing  │ None (zero probability for       │ Laplace (add-α, α=0.5) — every   │
+ │                   │ unseen transitions)              │ state in vocab gets nonzero mass │
+ ├───────────────────┼──────────────────────────────────┼──────────────────────────────────┤
+ │ Model validation  │ Single 80/20 split               │ 80/20 plus 5-fold time-series CV │
+ │                   │                                  │ (mean ± std across folds)        │
+ ├───────────────────┼──────────────────────────────────┼──────────────────────────────────┤
+ │ Hook significance │ None (lift ≥ 1.15 → "hook")      │ Permutation test (500 shuffles)  │
+ │                   │                                  │ → p-value + ` * ** *** ` marks   │
+ ├───────────────────┼──────────────────────────────────┼──────────────────────────────────┤
+ │ Session boundary  │ Whole file = one session         │ Gap > 10 min or __user change    │
+ │                   │                                  │ → new segment, tagged per-event  │
+ └───────────────────┴──────────────────────────────────┴──────────────────────────────────┘
```

### $\color{#7ad7ff}{\textsf{What survives the upgrade}}$

- The **single-HTML-file output** — still no JavaScript framework, still `double-click to open`.
- **Stdlib only** — no `pip install`, no `virtualenv`, no `requirements.txt`.
- **Pure SVG rendering** — responsive, printable, accessible.
- **Zero network calls** — verified by the absence of any `http://` / `fetch(` / `XMLHttpRequest` outside the localhost relay allowlist.

---

## $\color{#00ffd1}{\textsf{Quick start (five minutes)}}$

You need Python (3.9+), a Chromium-family browser, and the free [Tampermonkey](https://www.tampermonkey.net/) extension.

### $\color{#ff4fd8}{\textsf{1 — Start the relay with a capture file}}$

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
# {"status":"ok","clients":0,"version":"2.0","ports":{"ws":8765,"http":8766},
#  "log":{"enabled":true,"path":"session.ndjson","written":0},
#  "kinds":{"request":0,"input":0,"visibility":0,"other":0},"broadcast_seq":0}
```

### $\color{#ff4fd8}{\textsf{2 — Open the visualizer (or the live portrait)}}$

$\color{#00ffd1}{\textsf{Option A — 3D cosmos}}$: double-click `Session_Cosmos/session_cosmos.html`. It opens in your default browser with a pre-built synthetic cosmos so the scene isn't empty on first launch.

On the right panel, click the **STREAM** tab, confirm the URL reads `ws://localhost:8765`, click **CONNECT**. The status pip should go cyan and read `STREAM LIVE`. The relay terminal will log the new client.

$\color{#ff4fd8}{\textsf{Option B — live mirror}}$: double-click `Reflex/reflex_live.html`. **New in v0.2.0.** Same WebSocket stream, but instead of 3D nodes you get all the Reflex analyses (rhythm, mix, hooks, crystal ball, coverage ring) updating every 750 ms as you browse. Open both at once and keep them side-by-side.

### $\color{#ff4fd8}{\textsf{3 — Install the userscript}}$

1. Click the Tampermonkey toolbar icon &rarr; **Create a new script**.
2. Delete the template. Paste the full contents of **`facebook-interceptor.user_2.js`** (v2.0 — supercharged with latency capture, offline buffer, sensors, multi-site support). If you prefer the leaner v1.1, use `facebook-interceptor.user_1.js`.
3. Save with Ctrl/Cmd+S. Make sure it shows as enabled in the Tampermonkey dashboard.

Visit [facebook.com](https://www.facebook.com). A neon HUD appears top-right &mdash; that's the interceptor. Scroll. Click between Home, Profile, Messenger, Marketplace. You'll see `captured` / `streamed` / `buffered` / `errors` counters climb and the `last activity` line update with friendly names like "Scrolling feed" or "Viewing a profile".

Switch back to the Session Cosmos tab &mdash; new nodes spawn in real time. The relay terminal logs every blob. `session.ndjson` grows on disk.

### $\color{#ff4fd8}{\textsf{4 — Run Reflex on what you captured}}$

```bash
cd ../Reflex
python reflex.py report ../Session_Cosmos/session.ndjson -o my_report.html --title "my session"
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


## $\color{#00ffd1}{\textsf{Architecture}}$

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


## $\color{#00ffd1}{\textsf{Session Cosmos in depth}}$

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

## $\color{#ff4fd8}{\textsf{Reflex in depth}}$

$\color{#00ffd1}{\textsf{ONE Python file}}$ (~2,700 lines in v0.2.0), $\color{#ff4fd8}{\textsf{THIRTEEN analyses}}$, $\color{#fff275}{\textsf{pure SVG output}}$. Each analysis is a pure function over a list of `Event` objects; each is paired with a `render_*()` function that emits an SVG string; the HTML template stitches them together with a Blade Runner observatory aesthetic.

To add your own analysis: write `analysis_*()` &rarr; `render_*()` &rarr; add a `section(...)` call inside `build_report()`.

> The full panel breakdown lives earlier in this README under [$\color{#ff4fd8}{\textsf{The 13 analysis panels}}$](#the-13-analysis-panels). The category taxonomy lives under [$\color{#ff4fd8}{\textsf{Taxonomy — 12 categories}}$](#taxonomy--12-categories). The stats behind each panel live under [$\color{#ff4fd8}{\textsf{Statistical rigor}}$](#statistical-rigor).

### $\color{#7ad7ff}{\textsf{Activity decoder}}$

Reflex classifies each request into one of 12 categories using **118 ordered regex patterns** against `fb_api_req_friendly_name`, then a `__url_path`-based fallback for blobs without a friendly_name. Unmatched names still fall through to a generic `Performing action` (mutations) or `Loading data` (queries) — but **v0.2.0 covers 97.9% of real traffic** against our captures. Extending the decoder is one-line-per-pattern: edit `ACTIVITY_PATTERNS` in [`Reflex/reflex.py`](Reflex/reflex.py), or feed unmatched names to [`reflex_discover.py`](Reflex/reflex_discover.py) to get auto-suggested clusters.

### $\color{#7ad7ff}{\textsf{CLI — subcommands}}$

```bash
# ─── classic single-session portrait ───
python reflex.py report capture.ndjson -o report.html --title "session"
python reflex.py capture.ndjson -o report.html             # legacy form — still works

# ─── decoder discovery ───
python reflex.py discover capture.ndjson                   # list unmatched friendly_names
python reflex_discover.py capture.ndjson --html d.html     # cluster + regex suggestions
python reflex_discover.py capture.ndjson --patch           # append to ACTIVITY_PATTERNS

# ─── cross-session diff — "you on Tuesday vs Saturday" ───
python reflex.py diff monday.ndjson saturday.ndjson -o diff.html \
                      --label-a "monday" --label-b "saturday"

# ─── longitudinal SQLite store (multi-week captures) ───
python reflex.py store ingest capture.ndjson
python reflex.py store list
python reflex.py store report <capture_id> -o longitudinal.html

# ─── real-time (run relay, install userscript v2, open this in browser) ───
python cosmos_relay.py --log session.ndjson    # starts relay v2.0
# then open Reflex/reflex_live.html in your browser — auto-connects to ws://127.0.0.1:8765
```

Generate your own synthetic session:

```bash
python generate_sample.py --events 2000 --seed 42 -o my_sample.ndjson
```

---

## $\color{#00ffd1}{\textsf{Repository layout}}$

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

## $\color{#ff4fd8}{\textsf{Privacy and ethics}}$

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

## $\color{#fff275}{\textsf{Troubleshooting}}$

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

## $\color{#9d7bff}{\textsf{Platform notes}}$

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

## $\color{#00ffd1}{\textsf{Roadmap}}$

### $\color{#00ffd1}{\textsf{Shipped in v0.1.x}}$

- `--log` flag on the relay writes captures directly to NDJSON _(relay v1.2)_
- Activity-context capture (`fb_api_req_friendly_name`) _(userscript v1.1)_
- Startup banner reports existing-line count for append-mode captures
- `/health` endpoint reports log status

### $\color{#ff4fd8}{\textsf{Shipped in v0.2.0}}$ — the supercharge

```diff
+ [x] 118-pattern decoder (was 41) — 97.9% coverage on real data
+ [x] 12-category taxonomy (was 6) — hover, ad, presence, react, notif_seen, self_surv
+ [x] Session segmentation (gap > 10 min or __user change → new segment)
+ [x] MAD-based burst detection (replaces biased μ+2σ on sparse sessions)
+ [x] Welch periodogram for dominant rhythm (replaces greedy first-max)
+ [x] Laplace-smoothed Markov model (no more zero probability unseen states)
+ [x] 5-fold time-series CV on predictions (catches distribution shift)
+ [x] Permutation test for hook significance (500 shuffles, p-value + stars)
+ [x] Cross-session diff — "you on Tuesday vs you on Saturday"
+ [x] Pattern-discovery tool: reflex_discover.py with char-trigram clustering
+ [x] Per-event latency capture (userscript v2.0 hooks fetch + XHR)
+ [x] Behavioral sensors: scroll velocity + tab visibility (__kind=input/visibility)
+ [x] localStorage buffer — userscript survives relay restarts, drains on reconnect
+ [x] Real-time Reflex: reflex_live.html — live portrait from WS stream
+ [x] Longitudinal SQLite store (multi-week captures, per-install user salting)
+ [x] Relay v2.0 multi-event-kind routing + monotonic __relay_seq broadcasts
+ [x] Instagram + Threads @match in userscript (same relay, same pipeline)
+ [x] BroadcastChannel + per-tab-id field for multi-tab coordination
+ [x] Six new analyses: hover-conversion, ad dose-response, rev-boundaries,
+     time-to-action survival, self-surveillance meta-layer, anomaly surfacing,
+     decoder self-diagnostic
```

### $\color{#fff275}{\textsf{Likely next}}$

- Per-surface breakdown of the Action–Response Envelope
- Export analyses as JSON for downstream ML pipelines
- PDF export (the report already has cyberpunk observatory aesthetic — perfect for print)
- Local-timezone diurnal portrait (currently UTC)
- Char n-gram embedding of friendly_names → unsupervised taxonomy growth
- Session-as-sequence embedding (nano-GPT over category tokens)
- UMAP of session embeddings across weeks — your behavior manifold
- Anomaly detection via isolation forest on engineered features

### $\color{#9d7bff}{\textsf{Third leg of the trilogy}}$ — **intervention** (unclaimed)

Session Cosmos **captures**, Reflex **analyses**. The unclaimed niche is $\color{#ff4fd8}{\textsf{INTERVENTION}}$ — a tool that, after you see your portrait, lets you set boundaries with yourself: block hook-moment patterns, mute your highest-lift categories, circuit-break your burst cadence, hijack Facebook's own `FBYRPTimeLimitsEnforcement` nag and replace it with *your own* chart. Candidate names: *Embargo*, *Parley*, *The Blinders*. If you build it, link back.

---

## $\color{#7ad7ff}{\textsf{Contributing}}$

Issues and PRs welcome. Small, focused changes over sweeping refactors. For new Reflex analyses, follow the `analysis_*()` &rarr; `render_*()` &rarr; `section(...)` pattern already in the file. For new decoder patterns, append to `ACTIVITY_PATTERNS` with a comment showing an example `friendly_name`. For relay changes, preserve stdlib-only and keep the startup output scannable.

If you capture something interesting on real data &mdash; unusual blob shapes, operation names that fall through the decoder, a diurnal portrait that surprises you &mdash; open an issue. The decoder's regex list was written from memory and is deliberately incomplete; real captures are how it grows.

---

## $\color{#5a8ca0}{\textsf{License}}$

MIT. Do what you want. Watch the watcher.

---

## $\color{#ff4fd8}{\textsf{Credits}}$

Built with [Claude](https://claude.ai). Aesthetic borrowed from late-night synthwave and the covers of old cyberpunk paperbacks.

## $\color{#00ffd1}{\textsf{Final Note}}$
Fuck off Mark
