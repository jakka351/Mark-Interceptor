#!/usr/bin/env python3
"""
Synthetic session generator for Reflex.

Produces an NDJSON file of captured Facebook-shaped blobs with realistic
structural patterns: diurnal rhythm, action-response coupling, burst
moments, habitual surface transitions. Deterministic via a fixed seed
so the sample report is reproducible.

Usage:   python generate_sample.py > sample_session.ndjson
         python generate_sample.py --events 500 --seed 42 > my_sample.ndjson
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone, timedelta

# Activities keyed by surface, labeled with realistic Facebook GraphQL operation names
SURFACE_ACTIVITIES = {
    'comet.fbweb.CometHomeRoute': [
        ('view', 'CometHomePageTimelineFeedRefetchQuery', 0.40),
        ('view', 'CometFeedStoryQuery', 0.25),
        ('view', 'CometFeedPaginateQuery', 0.15),
        ('act',  'CometUFIFeedbackLikeMutation', 0.08),
        ('compose', 'CometUFICommentCreateMutation', 0.04),
        ('act',  'CometSharePostMutation', 0.02),
        ('act',  'CometSavePostMutation', 0.01),
        ('nav',  'CometHomeRootQuery', 0.05),
    ],
    'comet.fbweb.CometProfileRoute': [
        ('view', 'CometProfileRootQuery', 0.45),
        ('view', 'CometProfileTimelineFeedQuery', 0.30),
        ('view', 'CometProfileFriendsQuery', 0.10),
        ('act',  'CometFriendingCometFriendRequestSendMutation', 0.06),
        ('act',  'CometFollowUserMutation', 0.05),
        ('act',  'CometUFIFeedbackLikeMutation', 0.04),
    ],
    'comet.fbweb.CometMessengerThreadRoute': [
        ('view', 'MessengerThreadQuery', 0.30),
        ('msg',  'MessengerMessageSendMutation', 0.30),
        ('msg',  'MessengerMarkReadMutation', 0.20),
        ('msg',  'MessengerTypingMutation', 0.15),
        ('msg',  'MessengerReactToMessageMutation', 0.05),
    ],
    'comet.fbweb.CometNotificationsRoute': [
        ('view', 'CometNotificationsListQuery', 0.60),
        ('act',  'CometNotificationMarkReadMutation', 0.35),
        ('view', 'CometNotificationDetailQuery', 0.05),
    ],
    'comet.fbweb.CometGroupRoute': [
        ('view', 'CometGroupRootQuery', 0.45),
        ('view', 'CometGroupFeedQuery', 0.35),
        ('act',  'CometUFIFeedbackLikeMutation', 0.10),
        ('compose', 'CometUFICommentCreateMutation', 0.06),
        ('act',  'CometGroupJoinMutation', 0.04),
    ],
    'comet.fbweb.CometMarketplaceRoute': [
        ('view', 'CometMarketplaceItemQuery', 0.50),
        ('search', 'CometMarketplaceSearchQuery', 0.30),
        ('view', 'CometMarketplaceHomeQuery', 0.15),
        ('act',  'CometMarketplaceSavedMutation', 0.05),
    ],
    'comet.fbweb.CometWatchRoute': [
        ('view', 'CometWatchHomeQuery', 0.40),
        ('view', 'CometVideoPlayerQuery', 0.45),
        ('act',  'CometUFIFeedbackLikeMutation', 0.10),
        ('compose', 'CometUFICommentCreateMutation', 0.05),
    ],
    'comet.fbweb.CometSearchRoute': [
        ('search', 'CometSearchResultsQuery', 0.85),
        ('search', 'CometSearchSuggestionQuery', 0.15),
    ],
    'comet.fbweb.CometSettingsRoute': [
        ('view', 'CometSettingsQuery', 0.80),
        ('act',  'CometSettingsUpdateMutation', 0.20),
    ],
}

# Habitual transition weights (probability of switching surface, given we decide to leave).
# Reflects typical user flow: home → profile → messenger, notifications → back to home, etc.
TRANSITION_WEIGHTS = {
    'comet.fbweb.CometHomeRoute': {
        'comet.fbweb.CometProfileRoute': 0.25,
        'comet.fbweb.CometMessengerThreadRoute': 0.20,
        'comet.fbweb.CometNotificationsRoute': 0.18,
        'comet.fbweb.CometWatchRoute': 0.12,
        'comet.fbweb.CometMarketplaceRoute': 0.10,
        'comet.fbweb.CometGroupRoute': 0.08,
        'comet.fbweb.CometSearchRoute': 0.05,
        'comet.fbweb.CometSettingsRoute': 0.02,
    },
    'comet.fbweb.CometProfileRoute': {
        'comet.fbweb.CometHomeRoute': 0.50,
        'comet.fbweb.CometMessengerThreadRoute': 0.25,
        'comet.fbweb.CometNotificationsRoute': 0.15,
        'comet.fbweb.CometProfileRoute': 0.10,  # different profile
    },
    'comet.fbweb.CometMessengerThreadRoute': {
        'comet.fbweb.CometMessengerThreadRoute': 0.40,  # different thread
        'comet.fbweb.CometHomeRoute': 0.40,
        'comet.fbweb.CometProfileRoute': 0.15,
        'comet.fbweb.CometNotificationsRoute': 0.05,
    },
    'comet.fbweb.CometNotificationsRoute': {
        'comet.fbweb.CometHomeRoute': 0.40,
        'comet.fbweb.CometProfileRoute': 0.30,
        'comet.fbweb.CometGroupRoute': 0.15,
        'comet.fbweb.CometWatchRoute': 0.10,
        'comet.fbweb.CometMessengerThreadRoute': 0.05,
    },
    'comet.fbweb.CometGroupRoute': {
        'comet.fbweb.CometHomeRoute': 0.40,
        'comet.fbweb.CometGroupRoute': 0.25,
        'comet.fbweb.CometProfileRoute': 0.20,
        'comet.fbweb.CometNotificationsRoute': 0.15,
    },
    'comet.fbweb.CometMarketplaceRoute': {
        'comet.fbweb.CometMarketplaceRoute': 0.50,
        'comet.fbweb.CometHomeRoute': 0.35,
        'comet.fbweb.CometSearchRoute': 0.15,
    },
    'comet.fbweb.CometWatchRoute': {
        'comet.fbweb.CometWatchRoute': 0.50,
        'comet.fbweb.CometHomeRoute': 0.35,
        'comet.fbweb.CometNotificationsRoute': 0.15,
    },
    'comet.fbweb.CometSearchRoute': {
        'comet.fbweb.CometHomeRoute': 0.35,
        'comet.fbweb.CometProfileRoute': 0.25,
        'comet.fbweb.CometMarketplaceRoute': 0.20,
        'comet.fbweb.CometGroupRoute': 0.20,
    },
    'comet.fbweb.CometSettingsRoute': {
        'comet.fbweb.CometHomeRoute': 0.70,
        'comet.fbweb.CometProfileRoute': 0.30,
    },
}


def weighted_choice(rng: random.Random, items: list, weight_idx: int = -1):
    """Given a list of tuples where one element is weight, pick one proportionally."""
    total = sum(x[weight_idx] for x in items)
    r = rng.random() * total
    cur = 0
    for x in items:
        cur += x[weight_idx]
        if r < cur:
            return x
    return items[-1]


def diurnal_activity_multiplier(hour: int) -> float:
    """
    Multiplier for activity density as a function of hour-of-day.
    Models typical late-evening doomscroll pattern: low daytime, peak 21:00-23:00,
    second bump at 07:00-09:00, very low 03:00-06:00.
    """
    # Bimodal: morning bump + evening peak
    morning = 0.8 * math.exp(-((hour - 8) ** 2) / 8)
    evening = 1.4 * math.exp(-((hour - 22) ** 2) / 6)
    daytime = 0.5
    night = 0.15 if 1 <= hour <= 5 else 1.0
    return max(0.15, (daytime + morning + evening) * night)


def generate_session(n_events: int, seed: int, start_ts: float | None = None) -> list[dict]:
    """Generate n_events blob dicts with realistic structure."""
    rng = random.Random(seed)

    # Session starts at a plausible moment — 3 days ago at an arbitrary hour
    if start_ts is None:
        # Start at a fixed moment (Monday 09:00 UTC, 3 days before now) for reproducibility
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(days=3)
        start_ts = start.timestamp()

    blobs = []
    current_surface = 'comet.fbweb.CometHomeRoute'
    ts = start_ts
    req_counter = rng.randint(100, 500)  # arbitrary starting __req

    # State: how many events we've been on current surface (for stay-prob)
    events_on_surface = 0

    # Action-response coupling: when an action happens, force the next few events
    # to be high-density view events on the same surface (simulating the algo serving more)
    amplification_remaining = 0

    # Rev change at 60% mark
    rev_change_idx = int(n_events * 0.6)
    rev_a = '1037554123'
    rev_b = '1037554587'

    # Occasional long quiet gaps
    for i in range(n_events):
        # Time advancement — respect diurnal pattern
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        mult = diurnal_activity_multiplier(hour)

        # Decide: do we leave the current surface this step?
        # Stay probability increases with amplification (algo-driven retention)
        base_stay = 0.75
        if amplification_remaining > 0:
            base_stay = 0.92
            amplification_remaining -= 1

        # Force occasional surface change regardless, for diversity
        if events_on_surface > 30:
            base_stay = 0.5

        if rng.random() > base_stay:
            # Leave current surface — pick next via TRANSITION_WEIGHTS
            weights = TRANSITION_WEIGHTS.get(current_surface, {'comet.fbweb.CometHomeRoute': 1.0})
            items = list(weights.items())
            total = sum(w for _, w in items)
            r = rng.random() * total
            cum = 0
            for route, w in items:
                cum += w
                if r < cum:
                    current_surface = route
                    break
            events_on_surface = 0
        else:
            events_on_surface += 1

        # Pick activity on current surface
        activities = SURFACE_ACTIVITIES.get(current_surface, SURFACE_ACTIVITIES['comet.fbweb.CometHomeRoute'])
        cat, friendly, _w = weighted_choice(rng, activities, weight_idx=2)

        # If this is an action, trigger amplification
        if cat in ('act', 'compose', 'msg') and amplification_remaining == 0:
            # 60% of the time, the algo amplifies — 15-25 extra retention events
            if rng.random() < 0.6:
                amplification_remaining = rng.randint(15, 25)

        # Time delta until next event — also diurnal-modulated
        # Normal: 0.5-4s between requests. Occasionally longer gap (user left app).
        if rng.random() < 0.03 / mult:
            gap = rng.uniform(60, 600)  # minutes-long gap
        else:
            gap = rng.uniform(0.4, 3.5) / mult

        # Connection quality
        r = rng.random()
        ccg = 'GOOD'
        if r < 0.02: ccg = 'BAD'
        elif r < 0.08: ccg = 'POOR'
        elif r < 0.18: ccg = 'MODERATE'
        elif r > 0.92: ccg = 'EXCELLENT'

        rev = rev_b if i >= rev_change_idx else rev_a

        blob = {
            '__a': '1',
            '__aaid': '0',
            '__ccg': ccg,
            '__comet_req': str(rng.randint(10, 50)),
            '__crn': current_surface,
            '__hs': '20560.HCSV2:comet_pkg.2.1...0',
            '__hsi': str(7629646184971383446 + i),
            '__req': _base36(req_counter),
            '__rev': rev,
            '__s': f'{rng.randrange(16**6):06x}:{rng.randrange(16**6):06x}:{rng.randrange(16**6):06x}',
            '__spin_b': 'trunk',
            '__spin_r': rev,
            '__spin_t': str(int(ts)),
            '__user': '100007854783134',
            'dpr': '1',
            'fb_dtsg': 'NAfvYIq5L6u5_SIM_' + str(rng.randrange(10000)),
            'jazoest': str(rng.randint(25000, 25999)),
            'lsd': f'{rng.randrange(36**20):020x}'[:22],
            'ph': 'C3',
            'fb_api_req_friendly_name': friendly,
            'fb_api_caller_class': 'RelayModern' + current_surface.split('.')[-1],
        }
        blobs.append(blob)

        ts += gap
        req_counter += 1

    return blobs


def _base36(n: int) -> str:
    if n == 0:
        return '0'
    digits = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(digits[r])
    return ''.join(reversed(out))


def main():
    p = argparse.ArgumentParser(description='Generate synthetic Reflex sample data')
    p.add_argument('--events', type=int, default=800, help='Number of events to generate')
    p.add_argument('--seed', type=int, default=1729, help='RNG seed for reproducibility')
    p.add_argument('-o', '--output', type=str, default=None, help='Output file (default: stdout)')
    args = p.parse_args()

    blobs = generate_session(args.events, args.seed)

    out = sys.stdout if args.output is None else open(args.output, 'w')
    try:
        for b in blobs:
            out.write(json.dumps(b) + '\n')
    finally:
        if args.output is not None:
            out.close()

    print(f"generated {len(blobs)} events", file=sys.stderr)


if __name__ == '__main__':
    main()
