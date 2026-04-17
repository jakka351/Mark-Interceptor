#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║  R E F L E X   ·   v0.1.0                                     ║
║                                                               ║
║  Mirror analysis for Session Cosmos captures.                 ║
║  Reads a newline-delimited JSON file of Facebook/Meta         ║
║  request telemetry and renders a single self-contained        ║
║  HTML portrait revealing the feedback loop between you        ║
║  and the ranking algorithm.                                   ║
║                                                               ║
║  Usage:  python reflex.py capture.ndjson -o report.html       ║
║                                                               ║
║  No network. Stdlib only. Inspect your own shadow.            ║
╚═══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VERSION = "0.1.0"


# ═══════════════════════════════════════════════════════════════
# ACTIVITY DECODER
# Turns fb_api_req_friendly_name into (label, icon, category)
# Categories: view | act | msg | compose | search | nav
# ═══════════════════════════════════════════════════════════════

ACTIVITY_PATTERNS = [
    # Messaging
    (r'Message.*Send|SendMessage|MessengerMessageSend',   'Sending a message',         '✉', 'msg'),
    (r'Message.*Read|ReadMessage|MarkRead',               'Reading messages',          '◉', 'msg'),
    (r'Message.*Typing|Typing',                           'Typing...',                 '✎', 'msg'),
    (r'Message.*Reaction|ReactToMessage',                 'Reacting to a message',     '♥', 'msg'),
    (r'MessengerThread|MessengerMessage',                 'Browsing messages',         '◈', 'msg'),
    (r'Messenger',                                        'Messenger activity',        '◈', 'msg'),

    # Social actions
    (r'FeedbackLike|ReactionsMutation|ReactToStory',      'Liking / reacting',         '♥', 'act'),
    (r'CommentCreate|AddComment',                         'Posting a comment',         '✎', 'compose'),
    (r'CommentEdit|EditComment',                          'Editing a comment',         '✎', 'compose'),
    (r'CommentDelete|DeleteComment',                      'Deleting a comment',        '✕', 'act'),
    (r'Share|SharePostMutation',                          'Sharing a post',            '↗', 'act'),
    (r'FriendRequestSend|SendFriendRequest',              'Sending friend request',    '+', 'act'),
    (r'FriendRequestAccept',                              'Accepting friend request',  '✓', 'act'),
    (r'Follow|SubscribeUser',                             'Following someone',         '+', 'act'),
    (r'Unfollow|UnsubscribeUser',                         'Unfollowing',               '-', 'act'),
    (r'GroupJoin|JoinGroup',                              'Joining a group',           '+', 'act'),
    (r'Save|BookmarkAdd',                                 'Saving a post',             '★', 'act'),
    (r'Hide|Snooze',                                      'Hiding content',            '◌', 'act'),
    (r'Report',                                           'Reporting content',         '⚑', 'act'),
    (r'Block',                                            'Blocking user',             '⊘', 'act'),

    # Composing
    (r'Composer.*Upload|UploadPhoto|UploadVideo',         'Uploading media',           '↑', 'compose'),
    (r'Composer.*Publish|PublishPost|CreatePost',         'Publishing a post',         '◆', 'compose'),
    (r'StoriesComposer',                                  'Creating a story',          '◆', 'compose'),
    (r'Composer',                                         'Composing...',              '✎', 'compose'),

    # Search
    (r'SearchResults|SearchQuery|SearchSuggestion',       'Searching',                 '◎', 'search'),
    (r'MarketplaceSearch',                                'Searching marketplace',     '◎', 'search'),

    # Profile & people
    (r'Profile.*Query|CometProfileRoot',                  'Viewing a profile',         '◉', 'view'),
    (r'FriendList',                                       'Browsing friends',          '◉', 'view'),

    # Feed & stories
    (r'HomePageTimelineFeed|HomeRoot',                    'Browsing home feed',        '≡', 'view'),
    (r'FeedStory|FeedRefetch|FeedPaginate',               'Scrolling feed',            '↓', 'view'),
    (r'StoryView|ViewStory',                              'Viewing a story',           '◉', 'view'),
    (r'WatchHome|WatchFeed|VideoPlayer',                  'Watching videos',           '▶', 'view'),

    # Surfaces
    (r'GroupRoot|GroupFeed',                              'Viewing a group',           '◉', 'view'),
    (r'Marketplace.*Item|MarketplaceProduct',             'Viewing a listing',         '◉', 'view'),
    (r'Marketplace',                                      'Browsing marketplace',      '≡', 'view'),
    (r'NotificationsList|NotificationFetch',              'Checking notifications',    '◉', 'view'),
    (r'NotificationMarkRead',                             'Reading notifications',     '✓', 'act'),

    # Nav / meta
    (r'Root.*Query$|PageQuery$|NavBar|SideBar',           'Loading page',              '↻', 'nav'),
    (r'Subscription$',                                    'Listening for updates',     '◌', 'nav'),
    (r'Settings',                                         'Adjusting settings',        '◈', 'act'),
    (r'Logout',                                           'Logging out',               '⊘', 'act'),
]

_COMPILED_PATTERNS = [(re.compile(p, re.I), label, icon, cat) for p, label, icon, cat in ACTIVITY_PATTERNS]


def decode_activity(friendly: str, route: str) -> tuple[str, str, str]:
    """Return (label, icon, category) for a given friendly_name + route."""
    if not friendly:
        if not route:
            return ('Unknown activity', '◌', 'nav')
        route_label = ROUTE_LABELS.get(route, 'Unknown')
        return (f'Browsing {route_label.lower()}', '≡', 'view')
    for rx, label, icon, cat in _COMPILED_PATTERNS:
        if rx.search(friendly):
            return (label, icon, cat)
    if friendly.endswith('Mutation'):
        return ('Performing action', '◆', 'act')
    if friendly.endswith('Query'):
        return ('Loading data', '≡', 'view')
    return ('Unknown activity', '◌', 'nav')


ROUTE_LABELS = {
    'comet.fbweb.CometHomeRoute':            'HOME FEED',
    'comet.fbweb.CometProfileRoute':         'PROFILE',
    'comet.fbweb.CometMessengerThreadRoute': 'MESSENGER',
    'comet.fbweb.CometNotificationsRoute':   'NOTIFICATIONS',
    'comet.fbweb.CometGroupRoute':           'GROUPS',
    'comet.fbweb.CometMarketplaceRoute':     'MARKETPLACE',
    'comet.fbweb.CometWatchRoute':           'WATCH',
    'comet.fbweb.CometSearchRoute':          'SEARCH',
    'comet.fbweb.CometSettingsRoute':        'SETTINGS',
}
ROUTE_COLORS = {
    'comet.fbweb.CometHomeRoute':            '#00ffd1',
    'comet.fbweb.CometProfileRoute':         '#ff4fd8',
    'comet.fbweb.CometMessengerThreadRoute': '#ffb347',
    'comet.fbweb.CometNotificationsRoute':   '#fff275',
    'comet.fbweb.CometGroupRoute':           '#9d7bff',
    'comet.fbweb.CometMarketplaceRoute':     '#66ff99',
    'comet.fbweb.CometWatchRoute':           '#ff6b6b',
    'comet.fbweb.CometSearchRoute':          '#7ad7ff',
    'comet.fbweb.CometSettingsRoute':        '#b8b8b8',
}
CATEGORY_COLORS = {
    'view':    '#7ad7ff',
    'act':     '#ff4fd8',
    'compose': '#fff275',
    'msg':     '#ffb347',
    'search':  '#9d7bff',
    'nav':     '#66ff99',
}


# ═══════════════════════════════════════════════════════════════
# EVENT MODEL + INGEST
# ═══════════════════════════════════════════════════════════════

@dataclass
class Event:
    req: int
    route: str
    timestamp: float
    ccg: str
    rev: Optional[str]
    friendly: str
    label: str
    icon: str
    category: str
    seq: int = 0  # ordinal in the session (filled by ingest)


def parse_req(val) -> int:
    if val is None:
        return 0
    try:
        return int(str(val), 36)
    except (ValueError, TypeError):
        return 0


def blob_to_event(blob: dict) -> Optional[Event]:
    """Convert a captured blob dict into an Event. Returns None if invalid."""
    req = parse_req(blob.get('__req'))
    route = blob.get('__crn') or ''
    ts_raw = blob.get('__spin_t')
    if not route or not ts_raw:
        return None
    try:
        ts = float(ts_raw)
    except (ValueError, TypeError):
        return None
    friendly = blob.get('fb_api_req_friendly_name') or ''
    label, icon, category = decode_activity(friendly, route)
    return Event(
        req=req, route=route, timestamp=ts,
        ccg=blob.get('__ccg') or 'GOOD',
        rev=blob.get('__rev'),
        friendly=friendly, label=label, icon=icon, category=category,
    )


def parse_ndjson(path: Path) -> list[Event]:
    """Parse a newline-delimited JSON file into a list of Events, sorted by req."""
    events: list[Event] = []
    with path.open('r', encoding='utf-8') as f:
        for line_num, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                blob = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  warning: line {line_num} skipped (invalid JSON): {e}", file=sys.stderr)
                continue
            # Skip relay control frames
            if isinstance(blob, dict) and blob.get('__type') == 'hello':
                continue
            ev = blob_to_event(blob) if isinstance(blob, dict) else None
            if ev:
                events.append(ev)
    # Sort by req (the monotonic request counter) as primary, timestamp as tiebreak
    events.sort(key=lambda e: (e.req, e.timestamp))
    # Dedupe on req (keep first)
    seen = set()
    deduped = []
    for e in events:
        if e.req in seen:
            continue
        seen.add(e.req)
        deduped.append(e)
    for i, e in enumerate(deduped):
        e.seq = i
    return deduped


# ═══════════════════════════════════════════════════════════════
# ANALYSES
# ═══════════════════════════════════════════════════════════════

def analysis_action_response(events: list[Event], window: int = 30) -> dict:
    """
    For each 'action' event (mutation), average the category-density
    of the WINDOW events before and after.
    Reveals the algorithm's response envelope to your taps.
    """
    action_cats = {'act', 'compose', 'msg'}
    action_indices = [i for i, e in enumerate(events) if e.category in action_cats]

    if len(action_indices) < 3:
        return {'available': False, 'reason': 'Not enough action events (need ≥3)'}

    # For each offset [-window, +window], collect event categories
    offsets = list(range(-window, window + 1))
    by_offset: dict[int, Counter] = {o: Counter() for o in offsets}

    for idx in action_indices:
        for o in offsets:
            j = idx + o
            if 0 <= j < len(events):
                by_offset[o][events[j].category] += 1

    # Normalize to fractions
    envelopes: dict[str, list[float]] = {cat: [] for cat in ('view', 'act', 'compose', 'msg', 'search', 'nav')}
    for o in offsets:
        total = sum(by_offset[o].values()) or 1
        for cat in envelopes:
            envelopes[cat].append(by_offset[o][cat] / total)

    return {
        'available': True,
        'offsets': offsets,
        'envelopes': envelopes,
        'n_actions': len(action_indices),
        'window': window,
    }


def analysis_transitions(events: list[Event]) -> dict:
    """Route-to-route transition matrix, normalized by row (probability of next given current)."""
    routes = sorted(set(e.route for e in events if e.route in ROUTE_LABELS))
    if len(routes) < 2:
        return {'available': False, 'reason': 'Not enough distinct surfaces'}

    counts = defaultdict(lambda: Counter())
    for i in range(len(events) - 1):
        a = events[i].route
        b = events[i + 1].route
        if a in ROUTE_LABELS and b in ROUTE_LABELS:
            counts[a][b] += 1

    # Normalize rows
    matrix = {}
    row_totals = {}
    for a in routes:
        row = counts[a]
        total = sum(row.values())
        row_totals[a] = total
        if total == 0:
            matrix[a] = {b: 0.0 for b in routes}
        else:
            matrix[a] = {b: row[b] / total for b in routes}

    # Also compute surface visit counts
    surface_visits = Counter(e.route for e in events if e.route in ROUTE_LABELS)

    return {
        'available': True,
        'routes': routes,
        'matrix': matrix,
        'row_totals': row_totals,
        'visits': dict(surface_visits),
    }


def analysis_rhythm(events: list[Event], bucket_seconds: int = 60) -> dict:
    """
    Activity density over time, bucketed by `bucket_seconds`.
    Also identifies burst moments (count > mean + 2*stdev).
    """
    if len(events) < 10:
        return {'available': False, 'reason': 'Not enough events'}

    t0 = events[0].timestamp
    t_end = events[-1].timestamp
    duration = max(1, t_end - t0)
    n_buckets = max(10, int(duration / bucket_seconds) + 1)
    buckets = [0] * n_buckets
    bucket_times = [t0 + i * bucket_seconds for i in range(n_buckets)]

    # Counts per bucket, split by category
    by_category = {cat: [0] * n_buckets for cat in CATEGORY_COLORS}

    for e in events:
        b = min(int((e.timestamp - t0) / bucket_seconds), n_buckets - 1)
        buckets[b] += 1
        if e.category in by_category:
            by_category[e.category][b] += 1

    # Burst detection
    nonzero = [b for b in buckets if b > 0]
    if len(nonzero) >= 3:
        mu = statistics.mean(nonzero)
        sd = statistics.stdev(nonzero) if len(nonzero) > 1 else 0
        threshold = mu + 2 * sd
        bursts = [i for i, v in enumerate(buckets) if v > threshold]
    else:
        mu = 0
        sd = 0
        threshold = 0
        bursts = []

    # Autocorrelation for periodicity
    centered = [b - (sum(buckets) / len(buckets)) for b in buckets]
    max_lag = min(60, len(buckets) // 2)
    autocorr = []
    denom = sum(x * x for x in centered) or 1
    for lag in range(max_lag):
        numer = sum(centered[i] * centered[i + lag] for i in range(len(centered) - lag))
        autocorr.append(numer / denom)

    # Find dominant period (ignore lag 0 and very short lags)
    dominant_period = None
    if len(autocorr) > 5:
        # Look for first local max after lag 2
        for i in range(3, len(autocorr) - 1):
            if autocorr[i] > autocorr[i - 1] and autocorr[i] > autocorr[i + 1] and autocorr[i] > 0.15:
                dominant_period = i * bucket_seconds
                break

    return {
        'available': True,
        'bucket_seconds': bucket_seconds,
        'n_buckets': n_buckets,
        'buckets': buckets,
        'by_category': by_category,
        'bucket_times': bucket_times,
        'bursts': bursts,
        'mean': mu,
        'threshold': threshold,
        'autocorr': autocorr,
        'dominant_period_seconds': dominant_period,
        't0': t0,
        't_end': t_end,
    }


def analysis_hooks(events: list[Event], lookback: int = 5) -> dict:
    """
    For each action event, look at the `lookback` events immediately before.
    Aggregates: what categories / surfaces precede your engagement?
    """
    action_cats = {'act', 'compose', 'msg'}
    action_indices = [i for i, e in enumerate(events) if e.category in action_cats]
    if len(action_indices) < 3:
        return {'available': False, 'reason': 'Not enough action events'}

    # What routes did you come from?
    preceding_routes = Counter()
    preceding_categories = Counter()
    for idx in action_indices:
        for o in range(1, lookback + 1):
            j = idx - o
            if j >= 0:
                preceding_routes[events[j].route] += 1
                preceding_categories[events[j].category] += 1

    # What action categories actually happened?
    triggered_cats = Counter(events[i].category for i in action_indices)
    triggered_labels = Counter(events[i].label for i in action_indices)

    # Session-wide category distribution (for comparison / baseline)
    baseline_cats = Counter(e.category for e in events)
    baseline_routes = Counter(e.route for e in events)

    # Lift = P(category | precedes action) / P(category)
    total_preceding = sum(preceding_categories.values()) or 1
    total_baseline = sum(baseline_cats.values()) or 1
    lifts = {}
    for cat in CATEGORY_COLORS:
        p_before = preceding_categories[cat] / total_preceding
        p_base = baseline_cats[cat] / total_baseline
        if p_base > 0.01:
            lifts[cat] = p_before / p_base
        else:
            lifts[cat] = 1.0

    return {
        'available': True,
        'n_actions': len(action_indices),
        'lookback': lookback,
        'preceding_routes': dict(preceding_routes),
        'preceding_categories': dict(preceding_categories),
        'triggered_categories': dict(triggered_cats),
        'triggered_labels': dict(triggered_labels.most_common(8)),
        'baseline_categories': dict(baseline_cats),
        'category_lifts': lifts,
    }


def analysis_diurnal(events: list[Event]) -> dict:
    """24-hour activity profile, split by category. Uses local time of the user."""
    if not events:
        return {'available': False, 'reason': 'No events'}

    # Bucket by hour-of-day (UTC for portability; user can note their TZ offset separately)
    by_hour: dict[int, Counter] = {h: Counter() for h in range(24)}
    totals = [0] * 24
    for e in events:
        try:
            dt = datetime.fromtimestamp(e.timestamp, tz=timezone.utc)
            h = dt.hour
            by_hour[h][e.category] += 1
            totals[h] += 1
        except (ValueError, OSError, OverflowError):
            continue

    max_count = max(totals) if totals else 1
    # Peak hour
    peak_hour = totals.index(max(totals)) if totals and max(totals) > 0 else None

    return {
        'available': True,
        'by_hour': {h: dict(c) for h, c in by_hour.items()},
        'totals': totals,
        'max_count': max_count,
        'peak_hour': peak_hour,
    }


def analysis_predictions(events: list[Event], train_frac: float = 0.8) -> dict:
    """
    Train a simple Markov model on the first `train_frac` of the session,
    then 'predict' the last portion. Reports accuracy numbers.
    Also exposes the learned model for the 'crystal ball' display.
    """
    if len(events) < 50:
        return {'available': False, 'reason': 'Need ≥50 events for meaningful train/test'}

    split = int(len(events) * train_frac)
    train = events[:split]
    test = events[split:]

    # Model: P(next_route | current_route) from training set
    transitions = defaultdict(Counter)
    for i in range(len(train) - 1):
        transitions[train[i].route][train[i + 1].route] += 1
    # Smoothed probabilities
    route_probs = {}
    for r, counts in transitions.items():
        total = sum(counts.values())
        route_probs[r] = {nxt: c / total for nxt, c in counts.items()}

    # P(next_category | current_category)
    cat_trans = defaultdict(Counter)
    for i in range(len(train) - 1):
        cat_trans[train[i].category][train[i + 1].category] += 1
    cat_probs = {}
    for c, counts in cat_trans.items():
        total = sum(counts.values())
        cat_probs[c] = {nxt: cnt / total for nxt, cnt in counts.items()}

    # Baseline: most common next route overall
    overall = Counter(e.route for e in train)
    baseline_route = overall.most_common(1)[0][0] if overall else None

    # Score on test set
    route_correct = 0
    route_top3_correct = 0
    cat_correct = 0
    baseline_correct = 0
    total = 0
    for i in range(len(test) - 1):
        cur = test[i]
        nxt = test[i + 1]
        total += 1

        # Route prediction
        pred = route_probs.get(cur.route, {})
        if pred:
            top_route = max(pred.items(), key=lambda kv: kv[1])[0]
            top3 = [r for r, _ in sorted(pred.items(), key=lambda kv: -kv[1])[:3]]
            if top_route == nxt.route:
                route_correct += 1
            if nxt.route in top3:
                route_top3_correct += 1

        # Category prediction
        cpred = cat_probs.get(cur.category, {})
        if cpred:
            top_cat = max(cpred.items(), key=lambda kv: kv[1])[0]
            if top_cat == nxt.category:
                cat_correct += 1

        # Baseline: always predict most common
        if baseline_route == nxt.route:
            baseline_correct += 1

    acc_route = route_correct / total if total else 0
    acc_route3 = route_top3_correct / total if total else 0
    acc_cat = cat_correct / total if total else 0
    acc_baseline = baseline_correct / total if total else 0

    # Current "crystal ball": given last event in session, what's the prediction?
    last = events[-1]
    next_route_dist = route_probs.get(last.route, {})
    next_cat_dist = cat_probs.get(last.category, {})
    top_next_route = sorted(next_route_dist.items(), key=lambda kv: -kv[1])[:5]
    top_next_cat = sorted(next_cat_dist.items(), key=lambda kv: -kv[1])[:5]

    # Probability of action in next k events (rough)
    # Using stationary distribution approximation
    if cat_probs:
        # Simulate: start from current category, iterate 5 steps, sum P(action)
        action_cats = {'act', 'compose', 'msg'}
        state = {last.category: 1.0}
        action_prob = 0.0
        decay = 1.0
        for _ in range(5):
            new_state = defaultdict(float)
            for c, p in state.items():
                trans = cat_probs.get(c, {})
                for nxt, tp in trans.items():
                    new_state[nxt] += p * tp
            state = dict(new_state)
            for c in action_cats:
                action_prob = 1 - (1 - action_prob) * (1 - state.get(c, 0) * decay)
            decay *= 0.8
    else:
        action_prob = 0.0

    return {
        'available': True,
        'train_size': len(train),
        'test_size': len(test),
        'route_accuracy': acc_route,
        'route_top3_accuracy': acc_route3,
        'category_accuracy': acc_cat,
        'baseline_accuracy': acc_baseline,
        'lift_over_baseline': acc_route / acc_baseline if acc_baseline > 0 else 0,
        'last_route': last.route,
        'last_category': last.category,
        'top_next_routes': top_next_route,
        'top_next_categories': top_next_cat,
        'action_prob_next5': action_prob,
    }


# ═══════════════════════════════════════════════════════════════
# SVG RENDERING PRIMITIVES
# ═══════════════════════════════════════════════════════════════

def svg_tag(w: int, h: int, *, viewbox: Optional[str] = None) -> str:
    vb = viewbox or f'0 0 {w} {h}'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="{vb}" class="plot" preserveAspectRatio="xMidYMid meet">'


def svg_grid(w: int, h: int, xs: int = 8, ys: int = 4, pad: int = 40) -> str:
    """Light grid background for plots."""
    parts = []
    for i in range(xs + 1):
        x = pad + (w - 2 * pad) * i / xs
        parts.append(f'<line x1="{x:.1f}" y1="{pad}" x2="{x:.1f}" y2="{h - pad}" class="grid-line"/>')
    for i in range(ys + 1):
        y = pad + (h - 2 * pad) * i / ys
        parts.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" class="grid-line"/>')
    return ''.join(parts)


def render_action_response(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    W, H = 900, 340
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 60, 50, 50
    offsets = data['offsets']
    envs = data['envelopes']
    n = len(offsets)
    zero_idx = offsets.index(0)

    parts = [svg_tag(W, H)]
    parts.append(svg_grid(W, H, xs=10, ys=5, pad=50))

    def x_for(i): return PAD_L + (W - PAD_L - PAD_R) * i / (n - 1)
    def y_for(v, max_v): return H - PAD_B - (H - PAD_T - PAD_B) * (v / max_v)

    center_x = x_for(zero_idx)

    # Shaded band at offset 0 (the action moment) — light pink bg to indicate "this is where you tapped"
    half_bw = (x_for(1) - x_for(0)) / 2
    parts.append(
        f'<rect x="{center_x - half_bw:.1f}" y="{PAD_T}" width="{half_bw*2:.1f}" '
        f'height="{H - PAD_T - PAD_B}" fill="#ff4fd8" opacity="0.08"/>'
    )
    parts.append(f'<line x1="{center_x:.1f}" y1="{PAD_T}" x2="{center_x:.1f}" y2="{H - PAD_B}" class="axis-mark"/>')
    parts.append(f'<text x="{center_x}" y="{PAD_T - 6}" class="label-sm" text-anchor="middle" fill="#ff4fd8">↓ YOU TAPPED</text>')

    # Focus the scale on the PASSIVE content response (view + search).
    # The action categories spike to 1.0 at offset 0 by construction (tautology) —
    # plotting those at full scale compresses the envelope we actually care about.
    passive_cats = ['view', 'search']
    passive_max = 0
    for cat in passive_cats:
        env = envs.get(cat, [])
        # ignore offset 0 itself for finding max (at offset 0 passive = 0 by construction)
        relevant = [v for i, v in enumerate(env) if i != zero_idx]
        if relevant:
            passive_max = max(passive_max, max(relevant))
    passive_max = max(passive_max, 0.01)
    # Round up a bit so line has headroom
    y_max = min(1.0, passive_max * 1.15)

    # Plot view (blue) and search (purple) — the algorithm's response
    for cat in passive_cats:
        env = envs.get(cat, [])
        if max(env) < 0.01:
            continue
        color = CATEGORY_COLORS[cat]
        pts = ' '.join(f'{x_for(i):.1f},{min(H - PAD_B - 1, y_for(v, y_max)):.1f}' for i, v in enumerate(env))
        # Area under line — subtle fill
        area = f'{PAD_L},{H - PAD_B} ' + pts + f' {W - PAD_R},{H - PAD_B}'
        parts.append(f'<polygon points="{area}" fill="{color}" opacity="0.08"/>')
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" opacity="0.95"/>')

    # Also plot act/msg/compose as THIN reference lines — just so the action spike is visible but not dominant
    for cat in ('act', 'msg', 'compose'):
        env = envs.get(cat, [])
        if max(env) < 0.01:
            continue
        color = CATEGORY_COLORS[cat]
        # Scale action lines to be visible but not dominant — cap at y_max too
        pts = ' '.join(f'{x_for(i):.1f},{min(H - PAD_B - 1, y_for(min(v, y_max), y_max)):.1f}' for i, v in enumerate(env))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1" opacity="0.5" stroke-dasharray="3,2"/>')

    # X axis labels
    for i, o in enumerate(offsets):
        if i % 10 == 0:
            x = x_for(i)
            parts.append(f'<text x="{x:.1f}" y="{H - PAD_B + 18}" class="label-sm" text-anchor="middle">{o:+d}</text>')
    parts.append(f'<text x="{W / 2}" y="{H - 10}" class="label-xs" text-anchor="middle" fill="#5a8ca0">offset from action (events)</text>')

    # Y axis labels
    parts.append(f'<text x="{PAD_L - 8}" y="{PAD_T + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">{y_max:.0%}</text>')
    parts.append(f'<text x="{PAD_L - 8}" y="{H - PAD_B + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">0%</text>')

    # Legend
    lx = W - PAD_R - 200
    ly = PAD_T + 12
    legend_items = [
        ('view', 'feed response', 'solid'),
        ('search', 'search response', 'solid'),
        ('act', 'your actions', 'dashed'),
    ]
    for cat, lbl, style in legend_items:
        if max(envs.get(cat, [0])) < 0.01:
            continue
        color = CATEGORY_COLORS[cat]
        dash = ' stroke-dasharray="3,2"' if style == 'dashed' else ''
        parts.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 20}" y2="{ly}" stroke="{color}" stroke-width="2"{dash}/>')
        parts.append(f'<text x="{lx + 26}" y="{ly + 4}" class="label-sm" fill="{color}">{lbl}</text>')
        ly += 16

    parts.append('</svg>')
    return ''.join(parts)


def render_transition_matrix(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    routes = data['routes']
    matrix = data['matrix']
    n = len(routes)

    CELL = 52
    PAD_L = 150
    PAD_T = 110
    W = PAD_L + n * CELL + 20
    H = PAD_T + n * CELL + 20

    parts = [svg_tag(W, H)]

    for j, col in enumerate(routes):
        label = ROUTE_LABELS.get(col, col)
        x = PAD_L + j * CELL + CELL / 2
        # Rotate -45 for less vertical overlap, anchor start so labels lean outward cleanly
        parts.append(
            f'<text x="{x}" y="{PAD_T - 10}" class="label-sm" text-anchor="start" '
            f'transform="rotate(-45 {x} {PAD_T - 10})" fill="{ROUTE_COLORS.get(col, "#aaa")}">{label}</text>'
        )

    for i, row in enumerate(routes):
        label = ROUTE_LABELS.get(row, row)
        y = PAD_T + i * CELL + CELL / 2 + 4
        parts.append(
            f'<text x="{PAD_L - 10}" y="{y}" class="label-sm" text-anchor="end" '
            f'fill="{ROUTE_COLORS.get(row, "#aaa")}">{label}</text>'
        )

    # Cells
    for i, row in enumerate(routes):
        for j, col in enumerate(routes):
            p = matrix[row].get(col, 0)
            x = PAD_L + j * CELL
            y = PAD_T + i * CELL
            # Color: glow intensity proportional to probability
            alpha = min(1.0, 0.15 + p * 1.4)
            color = ROUTE_COLORS.get(col, '#7ad7ff')
            parts.append(
                f'<rect x="{x + 2}" y="{y + 2}" width="{CELL - 4}" height="{CELL - 4}" '
                f'fill="{color}" fill-opacity="{alpha:.3f}" stroke="{color}" stroke-opacity="0.3" stroke-width="1"/>'
            )
            if p > 0.01:
                label_color = '#05060a' if alpha > 0.55 else '#e4f3fb'
                parts.append(
                    f'<text x="{x + CELL/2}" y="{y + CELL/2 + 4}" class="label-xs" '
                    f'text-anchor="middle" fill="{label_color}">{p*100:.0f}%</text>'
                )

    # Corner annotation
    parts.append(
        f'<text x="{PAD_L - 10}" y="{PAD_T - 40}" class="label-xs" text-anchor="end" fill="#5a8ca0">'
        f'FROM ↓ / TO →</text>'
    )

    parts.append('</svg>')
    return ''.join(parts)


def render_rhythm(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    W, H = 900, 280
    PAD = 40
    buckets = data['buckets']
    by_cat = data['by_category']
    bursts = set(data['bursts'])
    n = len(buckets)
    max_count = max(buckets) if buckets else 1

    parts = [svg_tag(W, H)]
    parts.append(svg_grid(W, H, xs=12, ys=4, pad=PAD))

    bw = (W - 2 * PAD) / n
    # Stacked bars by category
    stack_order = ['view', 'act', 'compose', 'msg', 'search', 'nav']
    for i in range(n):
        x = PAD + i * bw
        y_cursor = H - PAD
        for cat in stack_order:
            v = by_cat.get(cat, [0]*n)[i]
            if v == 0:
                continue
            h = (H - 2 * PAD) * (v / max_count)
            y_cursor -= h
            color = CATEGORY_COLORS[cat]
            parts.append(
                f'<rect x="{x:.1f}" y="{y_cursor:.1f}" width="{max(0.8, bw - 0.8):.1f}" height="{h:.1f}" '
                f'fill="{color}" opacity="0.85"/>'
            )
        # Burst marker
        if i in bursts:
            parts.append(
                f'<circle cx="{x + bw/2:.1f}" cy="{PAD + 8}" r="4" fill="#ff4fd8" opacity="0.9"/>'
            )

    # Axis labels
    parts.append(f'<text x="{PAD}" y="{H - PAD + 20}" class="label-sm">session start</text>')
    parts.append(f'<text x="{W - PAD}" y="{H - PAD + 20}" class="label-sm" text-anchor="end">session end</text>')
    parts.append(f'<text x="{PAD}" y="{PAD - 10}" class="label-sm" fill="#ff4fd8">● burst</text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_hooks(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    # Show category lifts as horizontal bars
    lifts = data['category_lifts']
    items = sorted(lifts.items(), key=lambda kv: -kv[1])

    W, H = 700, 260
    PAD_L = 110
    PAD_R = 60
    PAD_T = 40
    PAD_B = 30
    row_h = (H - PAD_T - PAD_B) / max(1, len(items))
    max_lift = max(max(v for _, v in items), 2.0)

    parts = [svg_tag(W, H)]
    # 1.0 reference line
    zero_x = PAD_L + (W - PAD_L - PAD_R) * (1.0 / max_lift)
    parts.append(f'<line x1="{zero_x:.1f}" y1="{PAD_T - 5}" x2="{zero_x:.1f}" y2="{H - PAD_B + 5}" class="axis-mark"/>')
    parts.append(f'<text x="{zero_x:.1f}" y="{PAD_T - 10}" class="label-xs" text-anchor="middle" fill="#5a8ca0">baseline 1×</text>')

    for i, (cat, lift) in enumerate(items):
        y = PAD_T + i * row_h + row_h / 2
        bar_w = (W - PAD_L - PAD_R) * (lift / max_lift)
        color = CATEGORY_COLORS.get(cat, '#888')
        parts.append(f'<text x="{PAD_L - 10}" y="{y + 4}" class="label-sm" text-anchor="end" fill="{color}">{cat}</text>')
        parts.append(f'<rect x="{PAD_L}" y="{y - row_h * 0.35:.1f}" width="{bar_w:.1f}" height="{row_h * 0.7:.1f}" fill="{color}" opacity="0.75"/>')
        parts.append(f'<text x="{PAD_L + bar_w + 6}" y="{y + 4}" class="label-sm" fill="{color}">{lift:.2f}×</text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_diurnal(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    W, H = 500, 500
    CX, CY = W / 2, H / 2
    R_OUTER = 200
    R_INNER = 60

    totals = data['totals']
    by_hour = data['by_hour']
    max_count = data['max_count'] or 1
    peak = data['peak_hour']

    parts = [svg_tag(W, H)]

    # Hour ring markers
    for h in range(24):
        angle = (h / 24) * 2 * math.pi - math.pi / 2
        x1 = CX + (R_OUTER + 6) * math.cos(angle)
        y1 = CY + (R_OUTER + 6) * math.sin(angle)
        x2 = CX + (R_OUTER + 14) * math.cos(angle)
        y2 = CY + (R_OUTER + 14) * math.sin(angle)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="tick"/>')
        if h % 3 == 0:
            lx = CX + (R_OUTER + 30) * math.cos(angle)
            ly = CY + (R_OUTER + 30) * math.sin(angle) + 4
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" class="label-sm" text-anchor="middle">{h:02d}</text>')

    # Concentric rings
    for frac in (0.25, 0.5, 0.75, 1.0):
        r = R_INNER + (R_OUTER - R_INNER) * frac
        parts.append(f'<circle cx="{CX}" cy="{CY}" r="{r:.1f}" fill="none" class="ring"/>')

    # Stacked category wedges per hour
    stack_order = ['view', 'act', 'compose', 'msg', 'search', 'nav']
    slice_angle = 2 * math.pi / 24
    for h in range(24):
        base_angle = (h / 24) * 2 * math.pi - math.pi / 2
        a0 = base_angle - slice_angle / 2 + 0.01
        a1 = base_angle + slice_angle / 2 - 0.01
        hour_data = by_hour[h]
        total_h = sum(hour_data.values())
        if total_h == 0:
            continue
        cur_r = R_INNER
        for cat in stack_order:
            v = hour_data.get(cat, 0)
            if v == 0:
                continue
            frac = v / max_count
            new_r = cur_r + (R_OUTER - R_INNER) * frac
            # Draw annular wedge
            x0o = CX + new_r * math.cos(a0); y0o = CY + new_r * math.sin(a0)
            x1o = CX + new_r * math.cos(a1); y1o = CY + new_r * math.sin(a1)
            x1i = CX + cur_r * math.cos(a1); y1i = CY + cur_r * math.sin(a1)
            x0i = CX + cur_r * math.cos(a0); y0i = CY + cur_r * math.sin(a0)
            large = 0
            path = (f'M {x0o:.1f},{y0o:.1f} A {new_r:.1f},{new_r:.1f} 0 {large} 1 {x1o:.1f},{y1o:.1f} '
                    f'L {x1i:.1f},{y1i:.1f} A {cur_r:.1f},{cur_r:.1f} 0 {large} 0 {x0i:.1f},{y0i:.1f} Z')
            color = CATEGORY_COLORS[cat]
            parts.append(f'<path d="{path}" fill="{color}" opacity="0.8"/>')
            cur_r = new_r

    # Peak hour marker
    if peak is not None and totals[peak] > 0:
        pa = (peak / 24) * 2 * math.pi - math.pi / 2
        px = CX + (R_OUTER + 48) * math.cos(pa)
        py = CY + (R_OUTER + 48) * math.sin(pa) + 4
        parts.append(f'<text x="{px:.1f}" y="{py:.1f}" class="label-sm" text-anchor="middle" fill="#ff4fd8">PEAK</text>')

    # Center label
    parts.append(f'<text x="{CX}" y="{CY - 4}" class="label-sm" text-anchor="middle" fill="#5a8ca0">24H</text>')
    parts.append(f'<text x="{CX}" y="{CY + 14}" class="label-xs" text-anchor="middle" fill="#5a8ca0">UTC</text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_predictions(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    W, H = 900, 420
    parts = [svg_tag(W, H)]

    # Left panel: accuracy bars
    PX, PY = 40, 40
    PW = 380
    labels = [
        ('model route', data['route_accuracy']),
        ('model top-3 route', data['route_top3_accuracy']),
        ('model category', data['category_accuracy']),
        ('baseline (mode)', data['baseline_accuracy']),
    ]
    row_h = 55
    for i, (lbl, acc) in enumerate(labels):
        y = PY + i * row_h
        is_model = 'model' in lbl
        color = '#00ffd1' if is_model else '#5a8ca0'
        bar_w = (PW - 140) * acc
        parts.append(f'<text x="{PX}" y="{y + 14}" class="label-sm" fill="#7ad7ff">{lbl}</text>')
        parts.append(f'<rect x="{PX}" y="{y + 20}" width="{PW - 140}" height="14" fill="#0a2030" stroke="#1a3848" stroke-width="1"/>')
        parts.append(f'<rect x="{PX}" y="{y + 20}" width="{bar_w:.1f}" height="14" fill="{color}" opacity="0.85"/>')
        parts.append(f'<text x="{PX + PW - 130}" y="{y + 31}" class="label-sm" fill="{color}">{acc*100:.1f}%</text>')

    # Right panel: crystal ball
    RX, RY = 480, 60
    RW = 380
    last_route_label = ROUTE_LABELS.get(data['last_route'], data['last_route'])
    last_color = ROUTE_COLORS.get(data['last_route'], '#7ad7ff')
    parts.append(f'<text x="{RX}" y="{RY}" class="label-xs" fill="#5a8ca0">◈ CRYSTAL BALL · if you kept going from here</text>')
    parts.append(f'<text x="{RX}" y="{RY + 20}" class="label-sm" fill="{last_color}">last surface: {last_route_label}</text>')

    # Top predicted next routes
    parts.append(f'<text x="{RX}" y="{RY + 58}" class="label-xs" fill="#5a8ca0">most likely next surface</text>')
    for i, (rt, p) in enumerate(data['top_next_routes'][:5]):
        y = RY + 78 + i * 30
        lbl = ROUTE_LABELS.get(rt, rt)
        c = ROUTE_COLORS.get(rt, '#7ad7ff')
        bar_w = (RW - 160) * p
        parts.append(f'<text x="{RX}" y="{y + 11}" class="label-sm" fill="{c}">{lbl}</text>')
        parts.append(f'<rect x="{RX + 120}" y="{y}" width="{RW - 160}" height="16" fill="#0a2030"/>')
        parts.append(f'<rect x="{RX + 120}" y="{y}" width="{bar_w:.1f}" height="16" fill="{c}" opacity="0.8"/>')
        parts.append(f'<text x="{RX + RW - 30}" y="{y + 12}" class="label-sm" fill="{c}" text-anchor="end">{p*100:.0f}%</text>')

    # P(action next 5)
    ap = data['action_prob_next5']
    gy = RY + 240
    parts.append(f'<text x="{RX}" y="{gy}" class="label-xs" fill="#5a8ca0">P(you take an action in the next 5 events)</text>')
    parts.append(f'<rect x="{RX}" y="{gy + 10}" width="{RW}" height="20" fill="#0a2030" stroke="#1a3848" stroke-width="1"/>')
    parts.append(f'<rect x="{RX}" y="{gy + 10}" width="{RW * ap:.1f}" height="20" fill="#ff4fd8" opacity="0.85"/>')
    parts.append(f'<text x="{RX + RW / 2}" y="{gy + 25}" class="label-sm" text-anchor="middle" fill="#fff">{ap*100:.1f}%</text>')

    parts.append('</svg>')
    return ''.join(parts)


# ═══════════════════════════════════════════════════════════════
# HTML ASSEMBLY
# ═══════════════════════════════════════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reflex · {title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Major+Mono+Display&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: #05060a; color: #e4f3fb;
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 14px; line-height: 1.6; }}
  body {{ padding: 48px 32px 120px; max-width: 1080px; margin: 0 auto; }}
  .scanlines {{ position: fixed; inset: 0; pointer-events: none;
    background: repeating-linear-gradient(0deg, rgba(255,255,255,0.014) 0px, rgba(255,255,255,0.014) 1px, transparent 1px, transparent 3px);
    mix-blend-mode: overlay; z-index: 100; }}
  header {{ margin-bottom: 60px; border-bottom: 1px solid rgba(0,255,209,0.2); padding-bottom: 28px; }}
  h1 {{ font-family: 'Major Mono Display', monospace; font-size: 44px;
    color: #00ffd1; letter-spacing: 0.12em;
    text-shadow: 0 0 24px rgba(0,255,209,0.5); margin-bottom: 6px; }}
  .subtitle {{ color: #ff4fd8; letter-spacing: 0.35em; font-size: 11px; margin-bottom: 18px; }}
  .meta {{ color: #5a8ca0; font-size: 11px; letter-spacing: 0.18em; }}
  .meta span {{ color: #7ad7ff; }}

  .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 48px; }}
  .stat-card {{ padding: 16px 18px; border: 1px solid rgba(0,255,209,0.2);
    background: rgba(5,25,35,0.4); }}
  .stat-card .v {{ font-size: 28px; color: #00ffd1; letter-spacing: 0.05em; font-weight: 500; display: block; }}
  .stat-card .l {{ color: #5a8ca0; font-size: 10px; letter-spacing: 0.25em; margin-top: 4px; }}

  section {{ margin-bottom: 60px; }}
  section h2 {{ color: #00ffd1; font-size: 14px; letter-spacing: 0.3em;
    margin-bottom: 8px; padding-bottom: 10px; border-bottom: 1px solid rgba(0,255,209,0.15); }}
  section .idx {{ color: #ff4fd8; margin-right: 10px; }}
  section .num {{ color: #5a8ca0; font-size: 11px; }}
  section .description {{ color: #b8d4e0; font-size: 12px; line-height: 1.75;
    max-width: 72ch; margin: 14px 0 20px; }}
  section .description em {{ color: #ff4fd8; font-style: normal; }}
  section .plot {{ display: block; margin: 0 auto; max-width: 100%; }}
  section .plot-narrow {{ max-width: 680px; margin: 0 auto; }}
  section .plot-narrow svg {{ width: 100%; height: auto; }}
  section .findings {{ margin-top: 20px; padding: 14px 18px;
    background: rgba(10,30,40,0.5); border-left: 2px solid #ff4fd8;
    font-size: 12px; color: #e4f3fb; }}
  section .findings strong {{ color: #ff4fd8; letter-spacing: 0.2em; font-size: 10px;
    display: block; margin-bottom: 6px; }}
  section .findings p {{ margin: 4px 0; }}

  .grid {{ fill: none; stroke: rgba(122,215,255,0.06); stroke-width: 1; }}
  .grid-line {{ stroke: rgba(122,215,255,0.08); stroke-width: 1; }}
  .axis-mark {{ stroke: #ff4fd8; stroke-width: 1; stroke-dasharray: 4,3; opacity: 0.5; }}
  .tick {{ stroke: #5a8ca0; stroke-width: 1; }}
  .ring {{ stroke: rgba(122,215,255,0.1); stroke-width: 1; }}
  .label-sm {{ fill: #7ad7ff; font-family: 'JetBrains Mono', monospace;
    font-size: 10px; letter-spacing: 0.15em; }}
  .label-xs {{ fill: #5a8ca0; font-family: 'JetBrains Mono', monospace;
    font-size: 9px; letter-spacing: 0.12em; }}
  .empty {{ padding: 30px; text-align: center; color: #5a8ca0;
    border: 1px dashed rgba(122,215,255,0.2); font-size: 11px; letter-spacing: 0.2em; }}

  footer {{ margin-top: 80px; padding-top: 24px; border-top: 1px solid rgba(0,255,209,0.15);
    color: #5a8ca0; font-size: 10px; letter-spacing: 0.2em; text-align: center; }}
  footer a {{ color: #7ad7ff; text-decoration: none; }}
  footer .ascii {{ color: #1a3848; font-size: 9px; line-height: 1; margin-bottom: 14px;
    white-space: pre; font-family: monospace; }}

  @media (max-width: 720px) {{
    .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
    h1 {{ font-size: 30px; }}
  }}
</style>
</head>
<body>
<div class="scanlines"></div>

<header>
  <h1>R E F L E X</h1>
  <div class="subtitle">MIRROR ANALYSIS · SESSION PORTRAIT</div>
  <div class="meta">
    generated <span>{generated}</span>
    &nbsp;·&nbsp; span <span>{span}</span>
    &nbsp;·&nbsp; events <span>{n_events}</span>
    &nbsp;·&nbsp; surfaces <span>{n_surfaces}</span>
  </div>
</header>

<div class="summary-grid">
  <div class="stat-card"><span class="v">{n_events}</span><div class="l">total events</div></div>
  <div class="stat-card"><span class="v">{n_actions}</span><div class="l">actions taken</div></div>
  <div class="stat-card"><span class="v">{n_surfaces}</span><div class="l">surfaces visited</div></div>
  <div class="stat-card"><span class="v">{duration_human}</span><div class="l">observed span</div></div>
</div>

{sections}

<footer>
  <div class="ascii">▓▒░ reflex v{version} ░▒▓</div>
  <div>self-portrait · rendered locally · no network · inspect the shadow</div>
</footer>

</body>
</html>
"""


SECTION_TEMPLATE = r"""<section id="{anchor}">
  <h2><span class="idx">◉</span><span class="num">{num} /</span> {title}</h2>
  <div class="description">{description}</div>
  {svg}
  {findings}
</section>"""


def section(num: str, title: str, description: str, svg: str, findings: Optional[str] = None, anchor: str = '', narrow: bool = False) -> str:
    f = ''
    if findings:
        f = f'<div class="findings"><strong>◈ OBSERVATION</strong>{findings}</div>'
    svg_html = f'<div class="plot-narrow">{svg}</div>' if narrow else svg
    return SECTION_TEMPLATE.format(
        anchor=anchor or title.lower().replace(' ', '-'),
        num=num, title=title.upper(),
        description=description, svg=svg_html, findings=f,
    )


def humanize_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
    return f"{int(seconds // 86400)}d {int((seconds % 86400) // 3600)}h"


def build_report(events: list[Event], title: str = 'session') -> str:
    # Analyses
    a_response = analysis_action_response(events)
    a_trans    = analysis_transitions(events)
    a_rhythm   = analysis_rhythm(events)
    a_hooks    = analysis_hooks(events)
    a_diurnal  = analysis_diurnal(events)
    a_predict  = analysis_predictions(events)

    n_events = len(events)
    n_actions = sum(1 for e in events if e.category in ('act', 'compose', 'msg'))
    n_surfaces = len(set(e.route for e in events))
    if events:
        duration = events[-1].timestamp - events[0].timestamp
    else:
        duration = 0

    # Findings (auto-generated observations)
    sections_html = []

    # 1 — ACTION RESPONSE
    findings_1 = None
    if a_response['available']:
        envs = a_response['envelopes']
        offsets = a_response['offsets']
        # Did view density change after action?
        zero_idx = offsets.index(0)
        view_before = statistics.mean(envs['view'][max(0, zero_idx - 10):zero_idx]) if zero_idx > 0 else 0
        view_after = statistics.mean(envs['view'][zero_idx + 1:zero_idx + 11]) if zero_idx + 11 < len(offsets) else view_before
        delta_pct = ((view_after - view_before) / view_before * 100) if view_before > 0 else 0
        direction = 'rose' if delta_pct > 5 else ('fell' if delta_pct < -5 else 'held roughly flat')
        findings_1 = (
            f"<p>Around your <em>{a_response['n_actions']} actions</em>, the density of passive "
            f"<em>view</em> events in the 10 requests immediately after the action {direction} "
            f"({delta_pct:+.0f}% vs the 10 requests before).</p>"
            f"<p>Translation: after you tap, the app served you "
            f"{('more' if delta_pct > 5 else 'less' if delta_pct < -5 else 'about the same amount of')} content to scroll past.</p>"
        )
    sections_html.append(section(
        '01', 'action — response envelope',
        "For every action you took — a like, a comment, a message, a share — Reflex "
        "averages the activity density in the <em>30 requests before</em> and <em>30 requests after</em> the moment you tapped. "
        "The shape of the resulting curve is the algorithm's reply, averaged into visibility. "
        "A spike on the right means the system reacted. A flat line means it didn't — or at least not in a way your own requests could see.",
        render_action_response(a_response), findings_1,
        anchor='action-response',
    ))

    # 2 — TRANSITIONS
    findings_2 = None
    if a_trans['available']:
        # Find the strongest "hidden gravitational pull": the highest transition probability out of each surface
        top_pulls = []
        for a, row in a_trans['matrix'].items():
            if a_trans['row_totals'][a] > 0:
                best = max(row.items(), key=lambda kv: kv[1])
                if best[0] != a and best[1] > 0.2:
                    top_pulls.append((a, best[0], best[1]))
        top_pulls.sort(key=lambda x: -x[2])
        if top_pulls:
            a, b, p = top_pulls[0]
            al = ROUTE_LABELS.get(a, a); bl = ROUTE_LABELS.get(b, b)
            findings_2 = (
                f"<p>Your strongest habitual pull: <em>{al} → {bl}</em> ({p*100:.0f}% of the time you leave {al}).</p>"
                f"<p>Muscle memory. Nobody decides to do this — you just end up there.</p>"
            )
    sections_html.append(section(
        '02', 'surface transition matrix',
        "The probability that going to any surface <em>next</em> given your current surface. "
        "Rows are your current location, columns are where you go next. A strong diagonal means you tend to stay where you are — deep scrolling. "
        "Bright off-diagonal cells reveal your habitual paths: the routes your attention takes without you ever consciously choosing.",
        render_transition_matrix(a_trans), findings_2,
        anchor='transitions', narrow=True,
    ))

    # 3 — RHYTHM
    findings_3 = None
    if a_rhythm['available']:
        n_bursts = len(a_rhythm['bursts'])
        burst_word = 'burst moment' if n_bursts == 1 else 'burst moments'
        period = a_rhythm.get('dominant_period_seconds')
        bp_min = period / 60 if period else None
        if bp_min:
            findings_3 = (
                f"<p>Detected <em>{n_bursts} {burst_word}</em> where activity exceeded "
                f"your baseline by more than 2σ.</p>"
                f"<p>Your session carries a dominant rhythm with a period of roughly "
                f"<em>{bp_min:.1f} minutes</em> — your attention oscillates at that rate.</p>"
            )
        else:
            findings_3 = (
                f"<p>Detected <em>{n_bursts} {burst_word}</em> where activity spiked above baseline.</p>"
                f"<p>No clear periodic rhythm — your session is arrhythmic, driven by external triggers rather than internal cycles.</p>"
            )
    sections_html.append(section(
        '03', 'session rhythm',
        "Activity density over time, bucketed by minute, stacked by category. "
        "The pink dots mark <em>burst moments</em> — buckets where your activity exceeded the session's baseline mean by more than 2 standard deviations. "
        "These are the moments you were really in it. Autocorrelation underneath reveals whether your session breathes at a regular cadence.",
        render_rhythm(a_rhythm), findings_3,
        anchor='rhythm',
    ))

    # 4 — HOOKS
    findings_4 = None
    if a_hooks['available']:
        lifts = a_hooks['category_lifts']
        # What category is most over-represented right before an action?
        by_lift = sorted([(c, v) for c, v in lifts.items() if c != 'nav'], key=lambda kv: -kv[1])
        if by_lift:
            top_cat, top_lift = by_lift[0]
            if top_lift > 1.15:
                findings_4 = (
                    f"<p>Events with category <em>{top_cat}</em> are <em>{top_lift:.2f}×</em> more "
                    f"likely to appear in the 5 requests immediately before you take an action, compared to baseline.</p>"
                    f"<p>In other words: when you see <em>{top_cat}</em> content, you're measurably more likely to respond.</p>"
                )
            else:
                findings_4 = "<p>No single category strongly predicts your actions — your engagement is spread evenly across contexts.</p>"
    sections_html.append(section(
        '04', 'hook moments',
        "For each action you took, Reflex looks at the <em>5 events immediately before</em> and measures which categories "
        "appear more often than their session-wide baseline. Lift values above 1.0× mean that category disproportionately "
        "precedes your taps — it's what gets you to act. This is the <em>hook</em>, empirically measured on you, by you.",
        render_hooks(a_hooks), findings_4,
        anchor='hooks',
    ))

    # 5 — DIURNAL
    findings_5 = None
    if a_diurnal['available'] and a_diurnal['peak_hour'] is not None:
        peak = a_diurnal['peak_hour']
        peak_count = a_diurnal['totals'][peak]
        total = sum(a_diurnal['totals'])
        frac = peak_count / total if total else 0
        findings_5 = (
            f"<p>Peak activity at <em>{peak:02d}:00 UTC</em> — "
            f"{frac*100:.0f}% of all observed events fall in that single hour.</p>"
            f"<p>This wheel is a clock. It tells you when you are most <em>available</em> to the feed.</p>"
        )
    sections_html.append(section(
        '05', 'diurnal portrait',
        "Your activity wrapped around a 24-hour clock, with each hour's petals colored by activity category. "
        "Length of a petal = total events in that hour. This is your temporal signature: the hours you belong to yourself, "
        "and the hours you belong to the feed.",
        render_diurnal(a_diurnal), findings_5,
        anchor='diurnal', narrow=True,
    ))

    # 6 — PREDICTIONS
    findings_6 = None
    if a_predict['available']:
        acc = a_predict['route_accuracy']
        base = a_predict['baseline_accuracy']
        lift = (acc / base) if base > 0 else 0
        top_next = a_predict['top_next_routes'][0] if a_predict['top_next_routes'] else None
        top_label = ROUTE_LABELS.get(top_next[0], top_next[0]) if top_next else '?'
        top_p = top_next[1] if top_next else 0
        findings_6 = (
            f"<p>A simple Markov model trained on the first 80% of your session predicts the next surface "
            f"with <em>{acc*100:.1f}%</em> accuracy on the held-out 20% — <em>{lift:.2f}×</em> better than guessing the most common surface.</p>"
            f"<p>From where you left off, the most likely next move is <em>{top_label}</em> ({top_p*100:.0f}% chance).</p>"
            f"<p>The mirror reflects. The mirror predicts.</p>"
        )
    sections_html.append(section(
        '06', 'prediction engine',
        "Reflex splits your session 80/20, trains a Markov model on the earlier chunk, and uses it to predict each next event "
        "in the later chunk. The accuracy bars on the left show how well that model performs against a naive baseline of always "
        "guessing your most-visited surface. The crystal ball on the right applies the fully-trained model to your <em>very last</em> "
        "event and asks: if you kept going right now, what would you probably do?",
        render_predictions(a_predict), findings_6,
        anchor='predictions',
    ))

    # Assemble
    generated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    if events:
        t_from = datetime.fromtimestamp(events[0].timestamp, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        t_to = datetime.fromtimestamp(events[-1].timestamp, tz=timezone.utc).strftime('%H:%M UTC')
        span = f'{t_from} → {t_to}'
    else:
        span = '—'

    return HTML_TEMPLATE.format(
        title=html_lib.escape(title),
        generated=generated,
        span=span,
        n_events=n_events,
        n_actions=n_actions,
        n_surfaces=n_surfaces,
        duration_human=humanize_duration(duration),
        version=VERSION,
        sections='\n'.join(sections_html),
    )


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main() -> int:
    p = argparse.ArgumentParser(
        description='Reflex — mirror analysis for Session Cosmos captures.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Reads a newline-delimited JSON file where each line is one captured Facebook/Meta
request blob (as produced by the Session Cosmos relay). Writes a single
self-contained HTML file containing six analyses of the feedback loop between
you and the algorithm.

  python reflex.py capture.ndjson -o report.html
  python reflex.py sample_session.ndjson -o docs/sample_report.html --title "sample session"
""")
    p.add_argument('input', type=Path, help='Path to NDJSON capture file')
    p.add_argument('-o', '--output', type=Path, default=Path('report.html'),
                   help='Output HTML file (default: report.html)')
    p.add_argument('--title', type=str, default='session', help='Title shown in report header')
    args = p.parse_args()

    if not args.input.exists():
        print(f"error: input file {args.input} not found", file=sys.stderr)
        return 1

    print(f"▸ reading {args.input}...", file=sys.stderr)
    events = parse_ndjson(args.input)
    if not events:
        print("error: no valid events found", file=sys.stderr)
        return 1
    print(f"  parsed {len(events)} events", file=sys.stderr)

    print("▸ running analyses...", file=sys.stderr)
    html_out = build_report(events, title=args.title)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_out, encoding='utf-8')
    print(f"▸ wrote {args.output} ({len(html_out):,} bytes)", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
