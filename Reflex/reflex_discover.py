#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║  R E F L E X _ D I S C O V E R                                ║
║                                                               ║
║  Auto-expands the ACTIVITY_PATTERNS catalog by clustering     ║
║  unmatched fb_api_req_friendly_name values from your real     ║
║  NDJSON captures.                                             ║
║                                                               ║
║  Given an NDJSON (or many), it:                               ║
║    1. Runs every friendly_name through reflex's current       ║
║       decoder.                                                ║
║    2. Groups the unmatched ones by character-trigram          ║
║       similarity (agglomerative, no deps).                    ║
║    3. For each cluster, proposes a regex + suggested          ║
║       category, label, icon.                                  ║
║    4. Writes a ready-to-paste Python snippet to stdout        ║
║       (and optionally patches reflex.py in place).            ║
║                                                               ║
║  Usage:                                                       ║
║    python reflex_discover.py capture.ndjson                   ║
║    python reflex_discover.py capture.ndjson --html out.html   ║
║    python reflex_discover.py capture.ndjson --patch           ║
║                                                               ║
║  Stdlib only. No network.                                     ║
╚═══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# Reuse the catalogue from reflex
sys.path.insert(0, str(Path(__file__).parent))
try:
    import reflex as R
except ImportError:
    print("error: reflex.py must be importable (same directory)", file=sys.stderr)
    sys.exit(2)

VERSION = "0.2.0"


# ═══════════════════════════════════════════════════════════════
# CHAR-TRIGRAM CLUSTERING
# ═══════════════════════════════════════════════════════════════

def trigrams(s: str) -> set:
    """Lowercased character trigrams (with word boundaries)."""
    s = '^^' + s.lower() + '$$'
    return {s[i:i + 3] for i in range(len(s) - 2)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def cluster_names(names: list[str], threshold: float = 0.45) -> list[list[str]]:
    """Agglomerative clustering with single-linkage using Jaccard similarity."""
    tgs = {n: trigrams(n) for n in names}
    clusters: list[list[str]] = [[n] for n in names]
    # Repeatedly merge closest pairs until none exceed threshold
    while True:
        best = None
        best_sim = threshold
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                # Representative: biggest member from each
                a = clusters[i][0]
                b = clusters[j][0]
                sim = jaccard(tgs[a], tgs[b])
                if sim > best_sim:
                    best_sim = sim
                    best = (i, j)
        if not best:
            break
        i, j = best
        clusters[i].extend(clusters[j])
        del clusters[j]
    # Sort clusters by size desc
    clusters.sort(key=lambda c: -len(c))
    return clusters


# ═══════════════════════════════════════════════════════════════
# SEMANTIC CATEGORY INFERENCE FROM CLUSTER CONTENT
# ═══════════════════════════════════════════════════════════════

SEMANTIC_HINTS = [
    # (regex, category, label, icon)
    (r'Hover|Tooltip|Preview',               'hover',       'Hovering',           '◉'),
    (r'AdsHalo|InstreamAd|Sponsored',        'ad',          'Ad exposure',        '◆'),
    (r'PresencePing|LastActive|Heartbeat',   'presence',    'Presence ping',      '●'),
    (r'ScreenTime|TimeLimit|ProductUsage',   'self_surv',   'FB tracking you',    '◎'),
    (r'SeenState|BadgeClear|MarkSeen',       'notif_seen',  'Seen ack',           '✓'),
    (r'Send.*Message|MessageSend|LS.*Send',  'msg',         'Sending a message',  '✉'),
    (r'Message|Thread|Messenger|Chat',       'msg',         'Messenger activity', '◈'),
    (r'FeedPagination|NewsFeed|HomeFeed',    'view',        'Scrolling feed',     '↓'),
    (r'Profile|Friends|Contacts|People',     'view',        'Browsing people',    '◉'),
    (r'Group',                               'view',        'Viewing groups',     '◉'),
    (r'Photo|Video|Watch|Story',             'view',        'Viewing media',      '◉'),
    (r'Comment.*Create|Post.*Create|Compose','compose',     'Composing',          '✎'),
    (r'UFIFeedback|React(?!ions)',           'react',       'Reacting',           '♥'),
    (r'Search',                              'search',      'Searching',          '◎'),
    (r'Block|Mute|Hide|Report|Snooze',       'act',         'Social action',      '⊘'),
    (r'Save|Bookmark',                       'act',         'Saving',             '★'),
    (r'Share',                               'act',         'Sharing',            '↗'),
    (r'Route.*Def|Nav|Sidebar|Header',       'nav',         'Navigation',         '↻'),
    (r'Setting|Config|Preferences|Gating',   'nav',         'Configuration',      '◈'),
    (r'Relay|Subscription|Prefetch',         'nav',         'Infra',              '◌'),
]
SEMANTIC_COMPILED = [(re.compile(p, re.I), c, l, i) for p, c, l, i in SEMANTIC_HINTS]


def infer_cluster_meta(cluster: list[str]) -> tuple[str, str, str]:
    """Infer (category, label, icon) from a cluster of friendly_names."""
    votes: Counter = Counter()
    for name in cluster:
        for rx, cat, label, icon in SEMANTIC_COMPILED:
            if rx.search(name):
                votes[(cat, label, icon)] += 1
                break
    if votes:
        return votes.most_common(1)[0][0]
    # Fallbacks based on ending
    rep = cluster[0]
    if rep.endswith('Mutation'):
        return ('act', 'Performing action', '◆')
    if rep.endswith('Query'):
        return ('view', 'Loading data', '≡')
    return ('nav', 'Unknown activity', '◌')


# ═══════════════════════════════════════════════════════════════
# REGEX SYNTHESIS — longest common substring, escaped
# ═══════════════════════════════════════════════════════════════

def longest_common_substring(strs: list[str]) -> str:
    if not strs:
        return ''
    if len(strs) == 1:
        return strs[0]
    shortest = min(strs, key=len)
    n = len(shortest)
    best = ''
    for length in range(n, 1, -1):
        for start in range(n - length + 1):
            candidate = shortest[start:start + length]
            if all(candidate in s for s in strs):
                if len(candidate) > len(best):
                    best = candidate
        if best:
            break
    return best


def cluster_to_regex(cluster: list[str]) -> str:
    """Turn a cluster of names into a sensible regex."""
    if len(cluster) == 1:
        # Just escape the whole thing
        return re.escape(cluster[0])
    lcs = longest_common_substring(cluster)
    if len(lcs) >= 4:
        return re.escape(lcs)
    # Fall back: top 3 members OR'd
    top = cluster[:3]
    return '|'.join(re.escape(n) for n in top)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def load_unmatched(paths: list[Path]) -> Counter:
    """Load NDJSONs and return counter of friendly_names that fall through the decoder."""
    unmatched: Counter = Counter()
    for path in paths:
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    blob = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(blob, dict):
                    continue
                fn = blob.get('fb_api_req_friendly_name')
                if not fn:
                    continue
                label, _, _ = R.decode_activity(fn, blob.get('__crn', ''), blob.get('__url_path', ''))
                if label in ('Performing action', 'Loading data', 'Unknown activity'):
                    unmatched[fn] += 1
    return unmatched


def render_html_report(clusters_with_meta: list, out_path: Path):
    """Pretty HTML view of discovered clusters + suggested patterns."""
    rows = []
    for i, (cluster, count, (cat, label, icon), regex) in enumerate(clusters_with_meta):
        color = R.CATEGORY_COLORS.get(cat, '#888')
        members = '<br>'.join(
            f'<code style="color:#b8d4e0">{R.html_lib.escape(n)}</code>' for n in cluster[:8]
        )
        if len(cluster) > 8:
            members += f'<br><em style="color:#5a8ca0">+ {len(cluster) - 8} more</em>'
        rows.append(f"""
<tr>
  <td style="color:#5a8ca0">{i + 1:02d}</td>
  <td style="color:{color};font-weight:700">{cat}</td>
  <td style="color:{color}">{icon} {label}</td>
  <td>{members}</td>
  <td style="color:#00ffd1"><code>{R.html_lib.escape(regex)}</code></td>
  <td style="color:#ff4fd8;text-align:right">{count}</td>
</tr>
""")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>reflex_discover — cluster report</title>
<style>
body {{ background:#05060a; color:#e4f3fb; font-family:ui-monospace,Menlo,monospace; font-size:12px; padding:30px; }}
h1 {{ color:#00ffd1; letter-spacing:0.2em; font-size:28px; margin-bottom:10px; }}
p {{ color:#b8d4e0; max-width:72ch; line-height:1.7; }}
table {{ width:100%; border-collapse:collapse; margin-top:30px; }}
th {{ text-align:left; padding:10px; color:#5a8ca0; border-bottom:1px solid rgba(0,255,209,0.2); font-size:10px; letter-spacing:0.25em; }}
td {{ padding:10px; vertical-align:top; border-bottom:1px solid rgba(0,255,209,0.08); }}
code {{ font-family:inherit; font-size:11px; }}
</style></head><body>
<h1>◎ R E F L E X _ D I S C O V E R</h1>
<p>Clusters of unmatched <code>fb_api_req_friendly_name</code> values from your capture.
Each row is a candidate pattern to paste into <code>ACTIVITY_PATTERNS</code> in <code>reflex.py</code>.</p>
<table>
<tr><th>#</th><th>cat</th><th>label</th><th>members</th><th>suggested regex</th><th>count</th></tr>
{''.join(rows)}
</table>
</body></html>
"""
    out_path.write_text(html, encoding='utf-8')


def emit_python_snippet(clusters_with_meta: list) -> str:
    """Return paste-ready Python additions to ACTIVITY_PATTERNS."""
    lines = [
        "# ─── Auto-generated by reflex_discover.py ─── PASTE INTO ACTIVITY_PATTERNS",
        "# Review before committing — regexes and categories are best-guess.",
        "",
    ]
    for cluster, count, (cat, label, icon), regex in clusters_with_meta:
        lines.append(
            f"    (r'{regex}', "
            f"'{label}', '{icon}', '{cat}'),   # {count}× — "
            f"{cluster[0][:48]}"
        )
    lines.append("")
    return '\n'.join(lines)


def patch_reflex_py(py_path: Path, snippet: str) -> int:
    """Insert the snippet right before the closing `]` of ACTIVITY_PATTERNS."""
    text = py_path.read_text(encoding='utf-8')
    marker = '_COMPILED_PATTERNS = [(re.compile(p, re.I)'
    if marker not in text:
        print("error: could not find ACTIVITY_PATTERNS terminator in reflex.py", file=sys.stderr)
        return 1
    # Find the closing ] immediately before the _COMPILED_PATTERNS line
    idx = text.find(marker)
    closing = text.rfind(']', 0, idx)
    if closing < 0:
        return 1
    # Insert before the closing bracket
    patched = text[:closing] + '\n' + snippet + '\n' + text[closing:]
    py_path.write_text(patched, encoding='utf-8')
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description='Reflex Discover — auto-grow the decoder from real captures.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('inputs', type=Path, nargs='+', help='One or more NDJSON capture files')
    p.add_argument('--threshold', type=float, default=0.45,
                   help='Jaccard trigram similarity threshold for clustering (default: 0.45)')
    p.add_argument('--min-count', type=int, default=2,
                   help='Only surface names seen at least this many times (default: 2)')
    p.add_argument('--html', type=Path, default=None,
                   help='Also write an HTML report to this path')
    p.add_argument('--patch', action='store_true',
                   help='Append discovered patterns directly to reflex.py (review the diff!)')
    args = p.parse_args()

    for path in args.inputs:
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return 1

    print(f"▸ loading {len(args.inputs)} capture(s)...", file=sys.stderr)
    unmatched = load_unmatched(args.inputs)
    if not unmatched:
        print("✓ 100% decoder coverage — nothing to discover.", file=sys.stderr)
        return 0

    # Filter by min count
    names = [n for n, c in unmatched.items() if c >= args.min_count]
    discarded = len(unmatched) - len(names)
    print(f"  {len(names)} unique unmatched names "
          f"(+{discarded} seen fewer than {args.min_count}× — skipped)", file=sys.stderr)

    print(f"▸ clustering (Jaccard trigram threshold={args.threshold})...", file=sys.stderr)
    clusters = cluster_names(names, threshold=args.threshold)
    print(f"  found {len(clusters)} cluster(s)", file=sys.stderr)

    # Enrich each cluster with count + inferred meta + regex
    clusters_with_meta = []
    for cluster in clusters:
        count = sum(unmatched[n] for n in cluster)
        meta = infer_cluster_meta(cluster)
        regex = cluster_to_regex(cluster)
        clusters_with_meta.append((cluster, count, meta, regex))
    clusters_with_meta.sort(key=lambda t: -t[1])

    print("\n" + "=" * 70, file=sys.stderr)
    for i, (cluster, count, (cat, label, icon), regex) in enumerate(clusters_with_meta):
        cat_c = R.CATEGORY_COLORS.get(cat, '#888')
        print(f"\n◉ cluster {i + 1} · {count}× total · {cat} · {icon} {label}", file=sys.stderr)
        for n in cluster[:6]:
            print(f"    {unmatched[n]:4d}×  {n}", file=sys.stderr)
        if len(cluster) > 6:
            print(f"    ... +{len(cluster) - 6} more", file=sys.stderr)
        print(f"    suggested regex: {regex}", file=sys.stderr)

    # Emit python snippet
    snippet = emit_python_snippet(clusters_with_meta)
    print("\n" + "=" * 70, file=sys.stderr)
    print("PASTE THIS INTO ACTIVITY_PATTERNS in reflex.py:", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print()
    print(snippet)

    if args.html:
        render_html_report(clusters_with_meta, args.html)
        print(f"\n▸ wrote HTML report to {args.html}", file=sys.stderr)

    if args.patch:
        py_path = Path(__file__).parent / 'reflex.py'
        print(f"\n▸ patching {py_path}... (review diff before committing!)", file=sys.stderr)
        rc = patch_reflex_py(py_path, snippet)
        if rc == 0:
            print("  ✓ patched. Re-run reflex.py to see improved coverage.", file=sys.stderr)
        return rc

    return 0


if __name__ == '__main__':
    sys.exit(main())
