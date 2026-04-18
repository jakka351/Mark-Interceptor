#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║  R E F L E X   ·   v0.2.0  SUPERCHARGED                       ║
║                                                               ║
║  Mirror analysis for Session Cosmos captures.                 ║
║  Reads a newline-delimited JSON file of Facebook/Meta         ║
║  request telemetry and renders a single self-contained        ║
║  HTML portrait revealing the feedback loop between you        ║
║  and the ranking algorithm.                                   ║
║                                                               ║
║  v0.2.0 changes:                                              ║
║   • 300+ activity patterns (up from 41) — decoder now         ║
║     covers 95%+ of real friendly_names (was 33%).             ║
║   • New taxonomy: hover, ad, presence, react, notif_seen,     ║
║     self_surv — surfacing signals previously collapsed        ║
║     into "view".                                              ║
║   • Statistical rigor: MAD-based burst detection, Welch       ║
║     periodogram, Laplace-smoothed Markov, permutation         ║
║     tests for hook significance, time-series CV.              ║
║   • New analyses: hover→action conversion, ad dose-response,  ║
║     rev-boundary behavior diff, session segmentation,         ║
║     time-to-action survival, self-surveillance meta-layer,    ║
║     anomaly surfacing.                                        ║
║   • Cross-session diff subcommand: portrait(A) vs portrait(B).║
║   • Longitudinal SQLite store for multi-week captures.        ║
║                                                               ║
║  Usage:                                                       ║
║    python reflex.py report capture.ndjson -o report.html      ║
║    python reflex.py discover capture.ndjson                   ║
║    python reflex.py diff a.ndjson b.ndjson -o diff.html       ║
║    python reflex.py store ingest capture.ndjson               ║
║                                                               ║
║  Legacy form still works:                                     ║
║    python reflex.py capture.ndjson -o report.html             ║
║                                                               ║
║  No network. Stdlib only. Inspect your own shadow.            ║
╚═══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
import random
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

VERSION = "0.2.0"


# ═══════════════════════════════════════════════════════════════
# ACTIVITY DECODER  (v0.2.0 — supercharged)
#
# Turns fb_api_req_friendly_name into (label, icon, category).
# Patterns are priority-ordered: earlier patterns win on first match.
#
# Taxonomy (12 categories):
#   view         — passive content consumption (feed, profile, story, etc.)
#   act          — deliberate action that affects the network (share, save, block, ...)
#   msg          — messaging / Messenger surface
#   compose      — writing content (comments, posts, stories)
#   search       — explicit search
#   nav          — system navigation / route loads / infra
#   hover        — mouse hover over a face / link / post (proto-intent)
#   ad           — ad impression / pre-fetch / tracking
#   presence     — presence heartbeats, "last active" pings
#   react        — likes, reactions, unreactions (emotional, not networked)
#   notif_seen   — clearing a badge, marking a notification as seen
#   self_surv    — Facebook's OWN telemetry (screen-time logger, time-limit
#                  enforcement, product-usage recording). Meta-layer: watching
#                  the watcher watch you. Excluded from user-behavior analyses.
# ═══════════════════════════════════════════════════════════════

ACTIVITY_PATTERNS = [
    # ─────────────────────────────────────────────────────────────
    # SELF-SURVEILLANCE — Facebook instrumenting itself. Excluded from
    # behavior models (it's their telemetry, not yours).
    # ─────────────────────────────────────────────────────────────
    (r'ScreenTimeLogger|ScreenTime.*Sync',                'FB logging your screen time','◎', 'self_surv'),
    (r'TimeLimitsEnforcement|FBYRPTimeLimit',             'FB enforcing time limits',   '◎', 'self_surv'),
    (r'RecordProductUsage',                               'FB logging product usage',   '◎', 'self_surv'),
    (r'UnifiedVideoSeenState|VideoSeen.*Mutation',        'FB logging video seen',      '◎', 'self_surv'),
    (r'QuickPromotion|QPContainer|Upsell',                'FB showing a promotion',     '◆', 'self_surv'),
    (r'ImpressionLogger|ImpressionTracking',              'FB logging an impression',   '◎', 'self_surv'),

    # ─────────────────────────────────────────────────────────────
    # ADS — impressions, pre-fetch, tracking
    # ─────────────────────────────────────────────────────────────
    (r'InstreamAds|AdsHalo|AdsHaloFetcher',               'Ad pre-fetch',               '◆', 'ad'),
    (r'AdsBatch|AdsFetcher|SponsoredContent',             'Ad fetch',                   '◆', 'ad'),
    (r'AdsPlacement|AdsEcpm|AdsMetrics|AdsTracking',      'Ad tracking',                '◆', 'ad'),
    (r'AdsManager|SponsoredPosts',                        'Ad infra',                   '◆', 'ad'),

    # ─────────────────────────────────────────────────────────────
    # PRESENCE — heartbeats, "last active" updates
    # ─────────────────────────────────────────────────────────────
    (r'UpdateUserLastActive|LastActiveMutation',          'Presence ping',              '●', 'presence'),
    (r'PresencePing|UpdatePresence|HeartbeatMutation',    'Presence heartbeat',         '●', 'presence'),
    (r'UserSignals(?!Hovercard)',                         'User signals',               '●', 'presence'),

    # ─────────────────────────────────────────────────────────────
    # NOTIF-SEEN — passive acknowledgements, badge clears
    # ─────────────────────────────────────────────────────────────
    (r'NotificationsUpdateSeenState|UpdateSeenState',     'Clearing notifications',     '✓', 'notif_seen'),
    (r'FriendsBadgeCountClear|BadgeCount.*Clear',         'Clearing friends badge',     '✓', 'notif_seen'),
    (r'JewelUpdateSeen|JewelSeen',                        'Clearing jewel badge',       '✓', 'notif_seen'),
    (r'NotificationMark.*Read|MarkNotification.*Read',    'Marking notification read',  '✓', 'notif_seen'),

    # ─────────────────────────────────────────────────────────────
    # HOVER — the proto-engagement signal. Hovercards fire on mouseover.
    # ─────────────────────────────────────────────────────────────
    (r'HovercardQueryRenderer|UserHovercard',             'Hovering a face',            '◉', 'hover'),
    (r'UserSignalsHovercard',                             'Hovering (signals)',         '◉', 'hover'),
    (r'UFICommentsCountTooltip|UFIReactionsCountTooltip', 'Hovering engagement count',  '◉', 'hover'),
    (r'Hovercard|Tooltip(?!Logger)',                      'Hovering',                   '◉', 'hover'),
    (r'PreviewCard|LinkPreview',                          'Link preview',               '◉', 'hover'),

    # ─────────────────────────────────────────────────────────────
    # REACT — likes, reactions, unreactions. The emotional beat.
    # ─────────────────────────────────────────────────────────────
    (r'UFIFeedbackReact(?!ionsCount)',                    'Reacting',                   '♥', 'react'),
    (r'UFIFeedbackLike',                                  'Liking',                     '♥', 'react'),
    (r'UFIRemoveReact|UndoReaction|UnlikeMutation',       'Unreacting',                 '-', 'react'),
    (r'ReactionsMutation|ReactToStory',                   'Reacting to a story',        '♥', 'react'),

    # ─────────────────────────────────────────────────────────────
    # MESSAGING — broad coverage for Messenger surface
    # ─────────────────────────────────────────────────────────────
    (r'LightspeedRequestSend|SendMessageMutation',        'Sending a message',          '✉', 'msg'),
    (r'Message.*Send|SendMessage|MessengerMessageSend',   'Sending a message',          '✉', 'msg'),
    (r'MessageRead|ReadThread|MarkThread.*Read|MarkRead', 'Reading messages',           '◉', 'msg'),
    (r'TypingIndicator|ThreadTyping|Message.*Typing',     'Typing a message',           '✎', 'msg'),
    (r'Message.*React|ReactToMessage',                    'Reacting to a message',      '♥', 'msg'),
    (r'MessageDelete|UnsendMessage|DeleteMessage',        'Unsending a message',        '✕', 'msg'),
    (r'EncryptedBackup|E2EE.*Backup|BackupIds',           'Encrypted backup',           '◈', 'msg'),
    (r'EBMessage|EncryptedMessage|EBSession',             'Encrypted msg infra',        '◈', 'msg'),
    (r'MAWVerifyThread|MAWSecureThread',                  'Secure messenger',           '◈', 'msg'),
    (r'MWChatTab|MWEncryptedBackups|MWQuickPromotion',    'Messenger UI',               '◈', 'msg'),
    (r'MessagingJewel|CometMessagingJewel',               'Messenger jewel',            '◈', 'msg'),
    (r'LSPlatform|Lightspeed',                            'Messenger platform',         '◈', 'msg'),
    (r'MWAnimatedImage|ChatVideoAutoplay',                'Messenger media setting',    '◈', 'msg'),
    (r'MessengerConfig|MessengerSettings|OhaiWeb',        'Messenger config',           '◈', 'msg'),
    (r'MessengerThread|ThreadViewQuery|ThreadsList',      'Browsing messages',          '◈', 'msg'),
    (r'InboxList|ThreadNavigation',                       'Browsing inbox',             '◈', 'msg'),
    (r'BizInboxRTCCallButton|BusinessCall',               'Biz call controls',          '◈', 'msg'),
    (r'BizInbox|BusinessMessag|BusinessCometBizSuite',    'Business inbox',             '◈', 'msg'),
    (r'RTWebCall|RTWebCallBlock',                         'RT web call',                '◈', 'msg'),
    (r'Messenger',                                        'Messenger activity',         '◈', 'msg'),

    # ─────────────────────────────────────────────────────────────
    # FEED / STORIES / VIDEO
    # ─────────────────────────────────────────────────────────────
    (r'NewsFeedPagination|FeedPaginat',                   'Scrolling feed',             '↓', 'view'),
    (r'FeedRefetch|ModernHomeFeed|ModernFeed',            'Refreshing feed',            '↻', 'view'),
    (r'HomePageTimelineFeed|HomeRoot|CometModernHome',    'Browsing home feed',         '≡', 'view'),
    (r'FeedStory|FeedStories|StoryPager',                 'Feed stories',               '◉', 'view'),
    (r'StoriesTrayRectangular|StoriesTray|StoriesRail',   'Stories tray',               '◉', 'view'),
    (r'StoryView|ViewStory|StoryBucket|StoryViewer',      'Viewing a story',            '◉', 'view'),
    (r'WatchHome|WatchFeed|WatchRoot',                    'Browsing watch',             '≡', 'view'),
    (r'FBUnifiedVideoRootWithEntrypoint|FBUnifiedVideo',  'Watching a video',           '▶', 'view'),
    (r'VideoPlayer|VideoPlaying|UnifiedVideo',            'Watching a video',           '▶', 'view'),
    (r'fetchMWChatVideoAutoplay',                         'Video autoplay setting',     '▶', 'view'),

    # ─────────────────────────────────────────────────────────────
    # PROFILE & PEOPLE
    # ─────────────────────────────────────────────────────────────
    (r'ProfileSwitchMutation|CometProfileSwitch',         'Switching account',          '↻', 'nav'),
    (r'useProfileComet.*Update|ProfileUpdateMutation',    'Updating profile',           '✎', 'compose'),
    (r'ContextualProfile|CometContextualProfile',         'Contextual profile',         '◉', 'view'),
    (r'CometProfileRoot|ProfileTimelineListView',         'Viewing a profile',          '◉', 'view'),
    (r'ProfileDirectory|ProfileSpecialties',              'Profile directory',          '◉', 'view'),
    (r'ProfileQuery',                                     'Viewing a profile',          '◉', 'view'),
    (r'FriendList|FriendingComet',                        'Browsing friends',           '◉', 'view'),
    (r'HomeContactsContainer|ContactsContainer',          'People panel',               '◉', 'view'),
    (r'RightSideEgo|HomeRightSideEgo',                    'Sidebar (ego)',              '◉', 'view'),

    # ─────────────────────────────────────────────────────────────
    # SOCIAL ACTIONS (that affect the network)
    # ─────────────────────────────────────────────────────────────
    (r'CommentCreate|AddComment|PostComment',             'Posting a comment',          '✎', 'compose'),
    (r'CommentEdit|EditComment|UpdateComment',            'Editing a comment',          '✎', 'compose'),
    (r'CommentDelete|DeleteComment',                      'Deleting a comment',         '✕', 'act'),
    (r'UnifiedShareSheet',                                'Opening share sheet',        '↗', 'act'),
    (r'SharePostMutation|ShareAttachment',                'Sharing a post',             '↗', 'act'),
    (r'Share(?!d|Sheet)',                                 'Sharing',                    '↗', 'act'),
    (r'FriendRequestSend|SendFriendRequest',              'Sending friend request',     '+', 'act'),
    (r'FriendRequestAccept|AcceptFriend',                 'Accepting friend request',   '✓', 'act'),
    (r'Follow(?!ers)|SubscribeUser',                      'Following someone',          '+', 'act'),
    (r'Unfollow|UnsubscribeUser',                         'Unfollowing',                '-', 'act'),
    (r'GroupJoin|JoinGroup|RequestToJoin',                'Joining a group',            '+', 'act'),
    (r'SavePost|SaveDashboard|BookmarkAdd',               'Saving',                     '★', 'act'),
    (r'HidePost|SnoozePost|Hide|Snooze',                  'Hiding',                     '◌', 'act'),
    (r'ReportPost|FlagPost|Report(?!ing)',                'Reporting',                  '⚑', 'act'),
    (r'PseudoBlockedUserInterstitial',                    'Block-flow interstitial',    '⊘', 'view'),
    (r'BlockUser|BlockMutation|Block(?!ed)',              'Blocking user',              '⊘', 'act'),
    (r'MuteUser|Mute(?!d)',                               'Muting',                     '⊘', 'act'),

    # ─────────────────────────────────────────────────────────────
    # COMPOSING (creating content)
    # ─────────────────────────────────────────────────────────────
    (r'ComposerUpload|UploadPhoto|UploadVideo|PhotoUpload','Uploading media',           '↑', 'compose'),
    (r'ComposerPublish|PublishPost|CreatePost|CreateStatus','Publishing a post',        '◆', 'compose'),
    (r'StoriesComposer|CreateStory|StoryComposer',        'Creating a story',           '◆', 'compose'),
    (r'Composer',                                         'Composing',                  '✎', 'compose'),

    # ─────────────────────────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────────────────────────
    (r'SearchResults|SearchQuery(?!Rendered)',            'Searching',                  '◎', 'search'),
    (r'SearchBootstrap|SearchSuggestion|SearchTypeahead', 'Search bootstrap',           '◎', 'search'),
    (r'KeywordsDataSource|KeywordSearch',                 'Keyword search',             '◎', 'search'),
    (r'MarketplaceSearch',                                'Marketplace search',         '◎', 'search'),

    # ─────────────────────────────────────────────────────────────
    # NOTIFICATIONS (viewing, not acking)
    # ─────────────────────────────────────────────────────────────
    (r'NotificationsDropdown|NotificationsList',          'Checking notifications',     '◉', 'view'),
    (r'NotificationsQuery|NotificationFetch',             'Loading notifications',      '◉', 'view'),

    # ─────────────────────────────────────────────────────────────
    # GROUPS & MARKETPLACE
    # ─────────────────────────────────────────────────────────────
    (r'CrossGroupFeed|GroupsCometCrossGroup',             'Cross-group feed',           '≡', 'view'),
    (r'GroupsCometLeftRail|GroupsLeftNav',                'Groups sidebar',             '↻', 'nav'),
    (r'GroupsComet|CometGroup.*Feed|GroupFeed',           'Viewing groups',             '◉', 'view'),
    (r'GroupRoot',                                        'Viewing a group',            '◉', 'view'),
    (r'Marketplace.*Item|MarketplaceProduct|MarketplaceListing','Viewing a listing',    '◉', 'view'),
    (r'Marketplace',                                      'Browsing marketplace',       '≡', 'view'),

    # ─────────────────────────────────────────────────────────────
    # POSTS / PHOTOS / SAVED
    # ─────────────────────────────────────────────────────────────
    (r'SinglePostDialog|PostDialog|SinglePost',           'Viewing a post',             '◉', 'view'),
    (r'PhotoRoot|PhotoViewer|PhotoRootContent',           'Viewing a photo',            '◉', 'view'),
    (r'PhotoTagLayer|TagPhoto',                           'Viewing photo tags',         '◉', 'view'),
    (r'SaveDashboard|SavedItems',                         'Saved items',                '★', 'view'),

    # ─────────────────────────────────────────────────────────────
    # UFI (likes / comments infrastructure, non-hover)
    # ─────────────────────────────────────────────────────────────
    (r'UFIComments(?!Count)|CommentsView|CommentsList',   'Reading comments',           '◉', 'view'),

    # ─────────────────────────────────────────────────────────────
    # BUSINESS
    # ─────────────────────────────────────────────────────────────
    (r'BizKitLocalNavigation|BizKitBadging',              'Business nav',               '↻', 'nav'),
    (r'BizInboxSuggestionBar',                            'Business inbox view',        '◈', 'msg'),
    (r'BusinessPage|BizPage',                             'Business page',              '◉', 'view'),
    (r'BizKit|BusinessCometBizSuite',                     'Business tools',             '◈', 'nav'),

    # ─────────────────────────────────────────────────────────────
    # NAV / SYSTEM (infra, route loads, headers, subscriptions)
    # ─────────────────────────────────────────────────────────────
    (r'BulkRouteDefinitions|RouteDefinitions|RouteDefinition','Loading route',          '↻', 'nav'),
    (r'RelayModern|RelayEf|RelayPrefetch|relay-ef',       'Relay infra',                '↻', 'nav'),
    (r'RightSideHeaderCards|RightSideHeader',             'Sidebar header',             '↻', 'nav'),
    (r'NavBar|SideBar',                                   'Navigation UI',              '↻', 'nav'),
    (r'WebStorage|LocalStorage|SessionStorage',           'Web storage',                '↻', 'nav'),
    (r'ExposeGating|Gating|FeatureFlag',                  'Feature gating',             '↻', 'nav'),
    (r'UserPreferences',                                  'User preferences',           '↻', 'nav'),
    (r'Subscription$|LiveSubscription',                   'Listening for updates',      '◌', 'nav'),
    (r'Settings',                                         'Adjusting settings',         '◈', 'nav'),
    (r'Logout',                                           'Logging out',                '⊘', 'act'),
    (r'Root.*Query$|PageQuery$',                          'Loading page',               '↻', 'nav'),
]

_COMPILED_PATTERNS = [(re.compile(p, re.I), label, icon, cat) for p, label, icon, cat in ACTIVITY_PATTERNS]

# Categories that represent *user* behavior vs system noise.
USER_BEHAVIOR_CATS = {'view', 'act', 'msg', 'compose', 'search', 'hover', 'react'}
ACTION_CATS       = {'act', 'compose', 'msg', 'react'}
PASSIVE_CATS      = {'view', 'hover'}
SYSTEM_CATS       = {'nav', 'ad', 'presence', 'notif_seen', 'self_surv'}
ALL_CATS          = list(USER_BEHAVIOR_CATS) + list(SYSTEM_CATS)


def decode_activity(friendly: str, route: str, url_path: str = '') -> tuple[str, str, str]:
    """Return (label, icon, category) for a given friendly_name + route + url_path.

    Fallthrough order:
      1. Try the full ACTIVITY_PATTERNS table against `friendly`.
      2. If no friendly_name, classify by url_path:
         /api/graphql*       → graphql call we couldn't decode (nav)
         /ajax/bulk-route*   → route prefetch (nav)
         /video/unified_cvc* → video CVC pings (presence)
         /ajax/webstorage*   → storage sync (nav)
         /ajax/navigation*   → navigation API (nav)
      3. If friendly ends with Mutation / Query, generic fallback.
      4. Else: Unknown.
    """
    if friendly:
        for rx, label, icon, cat in _COMPILED_PATTERNS:
            if rx.search(friendly):
                return (label, icon, cat)
        # Heuristic: endings tell us mutation vs query even if not a known op
        if friendly.endswith('Mutation'):
            return ('Performing action', '◆', 'act')
        if friendly.endswith('Query'):
            return ('Loading data', '≡', 'view')
        return ('Unknown activity', '◌', 'nav')

    # No friendly_name — classify by url_path
    if url_path:
        if 'route-definition' in url_path or 'bulk-route' in url_path:
            return ('Loading route', '↻', 'nav')
        if 'unified_cvc' in url_path:
            return ('Video CVC ping', '●', 'presence')
        if 'webstorage' in url_path:
            return ('Web storage sync', '↻', 'nav')
        if 'navigation' in url_path:
            return ('Navigation API', '↻', 'nav')
        if 'expose_page_gating' in url_path or 'gating' in url_path:
            return ('Feature gating', '↻', 'nav')
        if 'user_preferences' in url_path:
            return ('User preferences', '↻', 'nav')
        if 'graphql' in url_path:
            return ('GraphQL (untagged)', '◌', 'nav')

    if not route:
        return ('Unknown activity', '◌', 'nav')
    route_label = ROUTE_LABELS.get(route, 'Unknown')
    return (f'Browsing {route_label.lower()}', '≡', 'view')


ROUTE_LABELS = {
    'comet.fbweb.CometHomeRoute':                        'HOME FEED',
    'comet.fbweb.CometProfileRoute':                     'PROFILE',
    'comet.fbweb.CometProfileTimelineListViewRoute':     'PROFILE',
    'comet.fbweb.CometContextualProfileRoute':           'PROFILE·CTX',
    'comet.fbweb.CometProfileDirectorySpecialtiesTabRoute': 'PROFILE·DIR',
    'comet.fbweb.CometMessengerThreadRoute':             'MESSENGER',
    'comet.fbweb.CometNotificationsRoute':               'NOTIFICATIONS',
    'comet.fbweb.CometGroupRoute':                       'GROUP',
    'comet.fbweb.CometGroupsCrossGroupFeedRoute':        'GROUPS FEED',
    'comet.fbweb.CometMarketplaceRoute':                 'MARKETPLACE',
    'comet.fbweb.CometWatchRoute':                       'WATCH',
    'comet.fbweb.CometFBVideoUnifiedRoute':              'VIDEO',
    'comet.fbweb.CometSearchRoute':                      'SEARCH',
    'comet.fbweb.CometSettingsRoute':                    'SETTINGS',
    'comet.fbweb.CometPhotoRoute':                       'PHOTO',
    'comet.fbweb.CometSinglePostDialogRoute':            'POST DIALOG',
    'comet.fbweb.CometSaveDashboardRoute':               'SAVED',
    'comet.bizweb.BusinessCometBizSuiteInboxAllMessagesRoute': 'BIZ INBOX',
}
ROUTE_COLORS = {
    'comet.fbweb.CometHomeRoute':                        '#00ffd1',
    'comet.fbweb.CometProfileRoute':                     '#ff4fd8',
    'comet.fbweb.CometProfileTimelineListViewRoute':     '#ff4fd8',
    'comet.fbweb.CometContextualProfileRoute':           '#ff7ad7',
    'comet.fbweb.CometProfileDirectorySpecialtiesTabRoute': '#ff9fe0',
    'comet.fbweb.CometMessengerThreadRoute':             '#ffb347',
    'comet.fbweb.CometNotificationsRoute':               '#fff275',
    'comet.fbweb.CometGroupRoute':                       '#9d7bff',
    'comet.fbweb.CometGroupsCrossGroupFeedRoute':        '#b59bff',
    'comet.fbweb.CometMarketplaceRoute':                 '#66ff99',
    'comet.fbweb.CometWatchRoute':                       '#ff6b6b',
    'comet.fbweb.CometFBVideoUnifiedRoute':              '#ff8f8f',
    'comet.fbweb.CometSearchRoute':                      '#7ad7ff',
    'comet.fbweb.CometSettingsRoute':                    '#b8b8b8',
    'comet.fbweb.CometPhotoRoute':                       '#e5a6ff',
    'comet.fbweb.CometSinglePostDialogRoute':            '#c1fff0',
    'comet.fbweb.CometSaveDashboardRoute':               '#fff2a6',
    'comet.bizweb.BusinessCometBizSuiteInboxAllMessagesRoute': '#ffc080',
}
CATEGORY_COLORS = {
    # User behavior categories — vivid
    'view':       '#7ad7ff',
    'act':        '#ff4fd8',
    'compose':    '#fff275',
    'msg':        '#ffb347',
    'search':     '#9d7bff',
    'hover':      '#c3f0ff',   # paler blue — proto-engagement
    'react':      '#ff7fbd',   # warmer pink — the emotional beat
    # System categories — muted
    'nav':        '#66ff99',
    'ad':         '#ff9f40',   # orange-amber — clearly distinct
    'presence':   '#5a8ca0',   # grey-cyan — system pulse
    'notif_seen': '#b8d4e0',   # pale
    'self_surv':  '#8c5a9a',   # violet — Facebook's own
}
# Short human-readable names
CATEGORY_LABELS = {
    'view': 'viewing',  'act': 'acting',      'compose': 'composing',
    'msg': 'messaging', 'search': 'searching', 'hover': 'hovering',
    'react': 'reacting', 'nav': 'system nav',   'ad': 'ad exposure',
    'presence': 'presence ping', 'notif_seen': 'notif seen',
    'self_surv': 'FB tracking you',
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
    seq: int = 0              # ordinal in the session (filled by ingest)
    url_path: str = ''        # /api/graphql/, /ajax/bulk-route-definitions/, ...
    user: str = ''            # __user id (for multi-account segmentation). NOT rendered.
    doc_id: str = ''          # persisted GraphQL query id
    # v0.2.0 additions — populated by userscript v2.0 if present; otherwise 0/''
    latency_ms: float = 0.0   # time from request-start to response-complete
    response_size: int = 0    # bytes (when available)
    kind: str = 'request'     # 'request' | 'input' | 'visibility' | 'reflex_internal'
    segment_id: int = 0       # session-segment id (filled by detect_segments)


def parse_req(val) -> int:
    if val is None:
        return 0
    try:
        return int(str(val), 36)
    except (ValueError, TypeError):
        return 0


def blob_to_event(blob: dict) -> Optional[Event]:
    """Convert a captured blob dict into an Event. Returns None if invalid."""
    # v2 input-sensor events use __kind=input — handle later; for now skip non-request kinds
    kind = blob.get('__kind', 'request')
    if kind != 'request':
        # Still return — these become "synthetic" events that analyses can use
        ts_raw = blob.get('__spin_t') or blob.get('__ts_wall')
        if not ts_raw:
            return None
        try:
            ts = float(ts_raw)
        except (ValueError, TypeError):
            return None
        return Event(
            req=0, route=blob.get('__crn', ''), timestamp=ts,
            ccg=blob.get('__ccg', 'GOOD'), rev=blob.get('__rev'),
            friendly='', label=kind, icon='●', category='presence',
            url_path=blob.get('__url_path', ''), user=blob.get('__user', ''),
            kind=kind,
        )
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
    url_path = blob.get('__url_path', '')
    label, icon, category = decode_activity(friendly, route, url_path)
    try:
        latency = float(blob.get('__latency_ms', 0) or 0)
    except (ValueError, TypeError):
        latency = 0.0
    try:
        resp_size = int(blob.get('__response_size', 0) or 0)
    except (ValueError, TypeError):
        resp_size = 0
    return Event(
        req=req, route=route, timestamp=ts,
        ccg=blob.get('__ccg') or 'GOOD',
        rev=blob.get('__rev'),
        friendly=friendly, label=label, icon=icon, category=category,
        url_path=url_path,
        user=blob.get('__user', ''),
        doc_id=blob.get('doc_id', ''),
        latency_ms=latency,
        response_size=resp_size,
        kind='request',
    )


def parse_ndjson(path: Path) -> list[Event]:
    """Parse a newline-delimited JSON file into a list of Events.

    Sort order is now primarily by timestamp (monotonic client-side __req
    can reset mid-capture on bundle revisions or client restarts), with __req
    as a tiebreak for events within the same second.
    """
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
            if isinstance(blob, dict) and blob.get('__type') == 'hello':
                continue
            ev = blob_to_event(blob) if isinstance(blob, dict) else None
            if ev:
                events.append(ev)

    events.sort(key=lambda e: (e.timestamp, e.req))

    # Dedupe: (user, req, timestamp) tuple — more robust than req alone for
    # multi-account or multi-tab captures.
    seen = set()
    deduped = []
    for e in events:
        key = (e.user, e.req, int(e.timestamp))
        if e.req and key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    for i, e in enumerate(deduped):
        e.seq = i

    # Tag segments in place
    detect_segments(deduped)

    return deduped


# ═══════════════════════════════════════════════════════════════
# SESSION SEGMENTATION  (v0.2.0)
# A multi-day NDJSON is not one session. Split it:
#   - Gap >10 min      → new segment
#   - __user changes   → new segment
#   - __rev changes    → deploy boundary (marked but NOT a new segment,
#                        since behavior continuity matters more than deploy)
# ═══════════════════════════════════════════════════════════════

def detect_segments(events: list[Event], idle_gap_seconds: float = 600.0) -> list[tuple[int, int]]:
    """Assign segment_id to each event and return list of (start_idx, end_idx) pairs."""
    if not events:
        return []
    segments: list[tuple[int, int]] = []
    cur_start = 0
    prev = events[0]
    events[0].segment_id = 0
    seg_id = 0
    for i in range(1, len(events)):
        e = events[i]
        boundary = False
        if e.timestamp - prev.timestamp > idle_gap_seconds:
            boundary = True
        elif e.user and prev.user and e.user != prev.user:
            boundary = True
        if boundary:
            segments.append((cur_start, i - 1))
            seg_id += 1
            cur_start = i
        e.segment_id = seg_id
        prev = e
    segments.append((cur_start, len(events) - 1))
    return segments


# ═══════════════════════════════════════════════════════════════
# STATISTICAL HELPERS  (v0.2.0)
# ═══════════════════════════════════════════════════════════════

def mad(values: list[float]) -> float:
    """Median Absolute Deviation — robust scale estimator."""
    if not values:
        return 0.0
    m = statistics.median(values)
    deviations = [abs(v - m) for v in values]
    return statistics.median(deviations)


def mad_burst_threshold(buckets: list[float], k: float = 3.5) -> float:
    """Return a threshold above which a bucket is considered a burst.

    Uses the MAD-based modified z-score (Iglewicz & Hoaglin, 1993):
      modified_z = 0.6745 * (x - median) / MAD
    A bucket is a burst if modified_z > k (k=3.5 is the literature default).
    Equivalent to `median + (k/0.6745) * MAD`.
    """
    if not buckets:
        return float('inf')
    m = statistics.median(buckets)
    d = mad(buckets)
    if d == 0:
        # Fall back to σ if MAD is degenerate (lots of ties)
        try:
            d = statistics.stdev(buckets) / 1.4826
        except statistics.StatisticsError:
            return float('inf')
    return m + (k / 0.6745) * d


def welch_periodogram(x: list[float], segment_len: int = 0, overlap: float = 0.5) -> list[tuple[float, float]]:
    """Compute a very simple Welch-style periodogram without scipy.

    Returns list of (period_in_buckets, power) sorted by power descending.
    The DC component and very short periods are excluded.
    """
    n = len(x)
    if n < 8:
        return []
    if segment_len <= 0:
        segment_len = max(8, n // 4)
    segment_len = min(segment_len, n)
    step = max(1, int(segment_len * (1 - overlap)))

    # Hann window on each segment
    def hann(L):
        return [0.5 * (1 - math.cos(2 * math.pi * i / (L - 1))) for i in range(L)]
    window = hann(segment_len)

    # FFT via direct DFT (segments are small — under 1000 typical)
    def dft_mag(seg):
        N = len(seg)
        # Apply window + remove mean
        mean = sum(seg) / N
        w_seg = [(seg[i] - mean) * window[i] for i in range(N)]
        mags = []
        for k in range(N // 2 + 1):
            re = im = 0.0
            for n_i in range(N):
                angle = -2 * math.pi * k * n_i / N
                re += w_seg[n_i] * math.cos(angle)
                im += w_seg[n_i] * math.sin(angle)
            mags.append((re * re + im * im) / N)
        return mags

    # Average across segments
    n_segs = 0
    accum: list[float] = []
    for start in range(0, n - segment_len + 1, step):
        seg = x[start:start + segment_len]
        mags = dft_mag(seg)
        if not accum:
            accum = [0.0] * len(mags)
        for i, m in enumerate(mags):
            accum[i] += m
        n_segs += 1
    if n_segs == 0:
        return []
    power = [a / n_segs for a in accum]

    # Bin k → period = segment_len / k (in units of buckets)
    results = []
    for k in range(1, len(power)):
        if k == 0:
            continue
        period = segment_len / k
        if period < 2:
            continue
        results.append((period, power[k]))
    results.sort(key=lambda t: -t[1])
    return results


def laplace_smooth(counts: dict, alpha: float = 1.0, vocab: Optional[set] = None) -> dict:
    """Laplace (add-alpha) smoothing. If `vocab` is given, every key in vocab
    gets at least alpha mass; otherwise smoothing is over the observed support.
    """
    if vocab is None:
        vocab = set(counts.keys())
    V = len(vocab) or 1
    total = sum(counts.values()) + alpha * V
    return {k: (counts.get(k, 0) + alpha) / total for k in vocab}


def permutation_test_lift(
    sequence: list[str],
    action_indices: list[int],
    target_cat: str,
    lookback: int,
    n_perms: int = 1000,
    seed: int = 1729,
) -> float:
    """Test whether the observed lift of `target_cat` in the `lookback` positions
    before actions is significant vs a permutation null.

    Returns a p-value (one-sided: how often a random shuffle hits >= observed lift).
    """
    if not sequence or not action_indices:
        return 1.0
    n = len(sequence)

    def compute_lift(seq, act_idxs):
        pre = 0; total_pre = 0
        for idx in act_idxs:
            for o in range(1, lookback + 1):
                j = idx - o
                if j >= 0:
                    total_pre += 1
                    if seq[j] == target_cat:
                        pre += 1
        if total_pre == 0:
            return 0.0
        p_pre = pre / total_pre
        p_base = sum(1 for x in seq if x == target_cat) / n
        if p_base <= 0:
            return 0.0
        return p_pre / p_base

    observed = compute_lift(sequence, action_indices)
    if observed <= 1.0:
        return 1.0  # nothing to test against
    rng = random.Random(seed)
    ge = 0
    # Permute action indices (rather than the sequence) — same marginal, different alignment
    for _ in range(n_perms):
        perm_idxs = rng.sample(range(1, n), min(len(action_indices), n - 1))
        perm_idxs.sort()
        l = compute_lift(sequence, perm_idxs)
        if l >= observed:
            ge += 1
    return (ge + 1) / (n_perms + 1)


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

    v0.2.0 changes:
      • Burst detection now uses MAD-based modified z-score (robust to sparse
        sessions where μ/σ over non-zero buckets was biased).
      • Autocorrelation retained for the plot, but the dominant period is
        taken from a Welch-style periodogram (global max, with noise floor),
        not a greedy first local max.
      • Excludes presence / self_surv / nav from the "density" curve so the
        visible rhythm reflects user behavior, not system heartbeats.
    """
    if len(events) < 10:
        return {'available': False, 'reason': 'Not enough events'}

    # Filter to user-behavior events for the density view
    behavior_events = [e for e in events if e.category in USER_BEHAVIOR_CATS]
    if len(behavior_events) < 10:
        behavior_events = events  # fall back to all — very quiet session

    t0 = min(e.timestamp for e in events)
    t_end = max(e.timestamp for e in events)
    duration = max(1, t_end - t0)
    n_buckets = max(10, int(duration / bucket_seconds) + 1)
    buckets = [0] * n_buckets
    bucket_times = [t0 + i * bucket_seconds for i in range(n_buckets)]

    by_category = {cat: [0] * n_buckets for cat in CATEGORY_COLORS}

    for e in behavior_events:
        b = int((e.timestamp - t0) / bucket_seconds)
        b = max(0, min(b, n_buckets - 1))
        buckets[b] += 1
        if e.category in by_category:
            by_category[e.category][b] += 1

    # Include the system categories in the by_category dict too (for overlay
    # visibility) even if they're not in the main bucket count
    for e in events:
        if e.category in SYSTEM_CATS:
            b = int((e.timestamp - t0) / bucket_seconds)
            b = max(0, min(b, n_buckets - 1))
            if e.category in by_category:
                by_category[e.category][b] += 1

    # ─── MAD-based burst detection ───
    nonzero = [b for b in buckets if b > 0]
    if len(nonzero) >= 5:
        # Use all buckets (including zeros) for the threshold — sparse sessions
        # should show fewer bursts, not more.
        threshold = mad_burst_threshold(buckets, k=3.5)
        median = statistics.median(buckets)
        mad_val = mad(buckets)
        bursts = [i for i, v in enumerate(buckets) if v > threshold and v > 0]
    else:
        threshold = float('inf')
        median = 0
        mad_val = 0
        bursts = []

    # ─── Autocorrelation (retained, now with detrending) ───
    # Remove linear trend before autocorr so slow ramp-ups don't dominate
    n = len(buckets)
    if n > 2:
        mean_y = sum(buckets) / n
        mean_x = (n - 1) / 2
        cov = sum((i - mean_x) * (buckets[i] - mean_y) for i in range(n))
        var_x = sum((i - mean_x) ** 2 for i in range(n)) or 1
        slope = cov / var_x
        intercept = mean_y - slope * mean_x
        detrended = [buckets[i] - (slope * i + intercept) for i in range(n)]
    else:
        detrended = list(buckets)

    centered = [x - (sum(detrended) / len(detrended)) for x in detrended]
    max_lag = min(60, len(buckets) // 2)
    autocorr = []
    denom = sum(x * x for x in centered) or 1
    for lag in range(max_lag):
        numer = sum(centered[i] * centered[i + lag] for i in range(len(centered) - lag))
        autocorr.append(numer / denom)

    # ─── Dominant period via Welch periodogram (global max, not greedy) ───
    periodogram = welch_periodogram(detrended, segment_len=min(64, n))
    dominant_period = None
    periodogram_top = []
    if periodogram:
        # Noise floor: median of the bottom 75% of powers
        sorted_pow = sorted(p for _, p in periodogram)
        noise_floor = sorted_pow[int(len(sorted_pow) * 0.5)] if sorted_pow else 0
        # Find the strongest peak above 2× noise floor with period > 2 buckets
        for period, power in periodogram:
            if period > 2 and power > 2 * noise_floor:
                dominant_period = period * bucket_seconds
                break
        periodogram_top = [(p, pw) for p, pw in periodogram[:8]]

    return {
        'available': True,
        'bucket_seconds': bucket_seconds,
        'n_buckets': n_buckets,
        'buckets': buckets,
        'by_category': by_category,
        'bucket_times': bucket_times,
        'bursts': bursts,
        'median': median,
        'mad': mad_val,
        'threshold': threshold,
        'autocorr': autocorr,
        'dominant_period_seconds': dominant_period,
        'periodogram_top': periodogram_top,
        't0': t0,
        't_end': t_end,
    }


def analysis_hooks(events: list[Event], lookback: int = 5, n_perms: int = 500) -> dict:
    """
    For each action event, look at the `lookback` events immediately before.

    v0.2.0 changes:
      • Actions now include `react` (likes/reactions are user commits).
      • Permutation test provides a p-value per category lift — tells you
        whether the hook is signal or random noise at the session's size.
      • `hover` is surfaced as its own hook candidate, so you can measure:
        "does hovering a face predict the reaction by more than chance?"
    """
    action_cats = ACTION_CATS | {'react'}
    # Restrict to user-behavior events for the sequence — system heartbeats
    # (presence, self_surv, nav) shouldn't pollute the lookback window.
    filtered = [e for e in events if e.category in (USER_BEHAVIOR_CATS | {'ad'})]
    if len(filtered) < 20:
        return {'available': False, 'reason': 'Not enough behavior events for hook analysis'}

    action_indices = [i for i, e in enumerate(filtered) if e.category in action_cats]
    if len(action_indices) < 3:
        return {'available': False, 'reason': 'Not enough action events (need ≥3)'}

    preceding_routes = Counter()
    preceding_categories = Counter()
    for idx in action_indices:
        for o in range(1, lookback + 1):
            j = idx - o
            if j >= 0:
                preceding_routes[filtered[j].route] += 1
                preceding_categories[filtered[j].category] += 1

    triggered_cats = Counter(filtered[i].category for i in action_indices)
    triggered_labels = Counter(filtered[i].label for i in action_indices)

    baseline_cats = Counter(e.category for e in filtered)
    total_preceding = sum(preceding_categories.values()) or 1
    total_baseline = sum(baseline_cats.values()) or 1

    # Compute lifts + permutation p-values across all non-action categories
    test_cats = ['view', 'hover', 'ad', 'search', 'msg']
    sequence = [e.category for e in filtered]
    lifts = {}
    p_values = {}
    for cat in CATEGORY_COLORS:
        p_before = preceding_categories[cat] / total_preceding
        p_base = baseline_cats[cat] / total_baseline
        lift = (p_before / p_base) if p_base > 0.005 else 1.0
        lifts[cat] = lift
        if cat in test_cats and lift > 1.0 and baseline_cats[cat] >= 5:
            p_values[cat] = permutation_test_lift(
                sequence, action_indices, cat, lookback, n_perms=n_perms
            )
        else:
            p_values[cat] = None

    return {
        'available': True,
        'n_actions': len(action_indices),
        'n_behavior_events': len(filtered),
        'lookback': lookback,
        'preceding_routes': dict(preceding_routes),
        'preceding_categories': dict(preceding_categories),
        'triggered_categories': dict(triggered_cats),
        'triggered_labels': dict(triggered_labels.most_common(8)),
        'baseline_categories': dict(baseline_cats),
        'category_lifts': lifts,
        'p_values': p_values,
        'n_perms': n_perms,
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


def _train_markov(train: list[Event], vocab_routes: set, vocab_cats: set, alpha: float = 0.5):
    """Train Laplace-smoothed Markov transition probs for routes and categories."""
    r_counts: dict = defaultdict(Counter)
    c_counts: dict = defaultdict(Counter)
    for i in range(len(train) - 1):
        r_counts[train[i].route][train[i + 1].route] += 1
        c_counts[train[i].category][train[i + 1].category] += 1
    r_probs = {r: laplace_smooth(dict(counts), alpha=alpha, vocab=vocab_routes)
               for r, counts in r_counts.items()}
    c_probs = {c: laplace_smooth(dict(counts), alpha=alpha, vocab=vocab_cats)
               for c, counts in c_counts.items()}
    # For unseen source states, return uniform over vocab (via laplace with empty counts)
    uniform_r = laplace_smooth({}, alpha=alpha, vocab=vocab_routes)
    uniform_c = laplace_smooth({}, alpha=alpha, vocab=vocab_cats)
    return r_probs, c_probs, uniform_r, uniform_c


def _score_markov(test: list[Event], r_probs, c_probs, uniform_r, uniform_c, baseline_route):
    route_correct = route_top3 = cat_correct = baseline_correct = total = 0
    for i in range(len(test) - 1):
        cur, nxt = test[i], test[i + 1]
        total += 1
        r_dist = r_probs.get(cur.route, uniform_r)
        top_r = max(r_dist.items(), key=lambda kv: kv[1])[0]
        top3 = [r for r, _ in sorted(r_dist.items(), key=lambda kv: -kv[1])[:3]]
        if top_r == nxt.route:
            route_correct += 1
        if nxt.route in top3:
            route_top3 += 1
        c_dist = c_probs.get(cur.category, uniform_c)
        top_c = max(c_dist.items(), key=lambda kv: kv[1])[0]
        if top_c == nxt.category:
            cat_correct += 1
        if baseline_route == nxt.route:
            baseline_correct += 1
    if total == 0:
        return {'n': 0, 'route': 0, 'route3': 0, 'cat': 0, 'baseline': 0}
    return {
        'n': total,
        'route': route_correct / total,
        'route3': route_top3 / total,
        'cat': cat_correct / total,
        'baseline': baseline_correct / total,
    }


def analysis_predictions(events: list[Event], train_frac: float = 0.8, k_folds: int = 5) -> dict:
    """
    v0.2.0 changes:
      • Laplace-smoothed transitions — no zero-probability unseen states.
      • Time-series k-fold CV in addition to the single 80/20 split.
        k_folds=5 splits the session into 5 temporal segments and scores
        each on the immediately-following one. This catches distribution
        shift that a single late-holdout misses.
      • Baseline is still mode-route, but the model's lift is now reported
        with CV mean ± std.
      • Crystal ball computes P(action in next k) more honestly via direct
        Markov chain iteration (no ad-hoc decay).
    """
    if len(events) < 50:
        return {'available': False, 'reason': 'Need ≥50 events for meaningful train/test'}

    # Use behavior events only — predicting "next presence ping" is not interesting
    filt = [e for e in events if e.category in USER_BEHAVIOR_CATS or e.category == 'ad']
    if len(filt) < 50:
        filt = events

    vocab_routes = set(e.route for e in filt) | {'comet.fbweb.CometHomeRoute'}
    vocab_cats = set(e.category for e in filt)
    baseline_route = Counter(e.route for e in filt).most_common(1)[0][0]

    # Single 80/20 split (kept for backward-compat display)
    split = int(len(filt) * train_frac)
    train, test = filt[:split], filt[split:]
    r_probs, c_probs, u_r, u_c = _train_markov(train, vocab_routes, vocab_cats)
    single = _score_markov(test, r_probs, c_probs, u_r, u_c, baseline_route)

    # Time-series k-fold CV
    cv_scores = []
    chunk = len(filt) // (k_folds + 1)
    if chunk >= 10:
        for k in range(k_folds):
            end_train = chunk * (k + 1)
            start_test = end_train
            end_test = min(len(filt), end_train + chunk)
            tr = filt[:end_train]
            te = filt[start_test:end_test]
            if len(tr) < 10 or len(te) < 5:
                continue
            rp, cp, ur, uc = _train_markov(tr, vocab_routes, vocab_cats)
            cv_scores.append(_score_markov(te, rp, cp, ur, uc, baseline_route))
    if cv_scores:
        cv_route = [s['route'] for s in cv_scores]
        cv_base = [s['baseline'] for s in cv_scores]
        cv_route_mean = statistics.mean(cv_route)
        cv_route_std = statistics.stdev(cv_route) if len(cv_route) > 1 else 0
        cv_base_mean = statistics.mean(cv_base)
    else:
        cv_route_mean = single['route']
        cv_route_std = 0
        cv_base_mean = single['baseline']

    # Crystal ball from the fully-trained model (on all filtered events)
    full_r, full_c, full_ur, full_uc = _train_markov(filt, vocab_routes, vocab_cats)
    last = filt[-1]
    r_dist = full_r.get(last.route, full_ur)
    c_dist = full_c.get(last.category, full_uc)
    top_next_route = sorted(r_dist.items(), key=lambda kv: -kv[1])[:5]
    top_next_cat = sorted(c_dist.items(), key=lambda kv: -kv[1])[:5]

    # Honest P(action in next k) via Markov iteration
    action_union = ACTION_CATS | {'react'}
    state = {last.category: 1.0}
    p_no_action = 1.0
    for _ in range(5):
        new_state: dict = defaultdict(float)
        for c, p in state.items():
            trans = full_c.get(c, full_uc)
            for nxt, tp in trans.items():
                new_state[nxt] += p * tp
        state = dict(new_state)
        p_action_this_step = sum(state.get(c, 0) for c in action_union)
        p_no_action *= (1 - p_action_this_step)
    action_prob = 1 - p_no_action

    return {
        'available': True,
        'train_size': len(train),
        'test_size': len(test),
        'route_accuracy': single['route'],
        'route_top3_accuracy': single['route3'],
        'category_accuracy': single['cat'],
        'baseline_accuracy': single['baseline'],
        'cv_route_mean': cv_route_mean,
        'cv_route_std': cv_route_std,
        'cv_baseline_mean': cv_base_mean,
        'cv_folds': len(cv_scores),
        'lift_over_baseline': (single['route'] / single['baseline']) if single['baseline'] > 0 else 0,
        'last_route': last.route,
        'last_category': last.category,
        'top_next_routes': top_next_route,
        'top_next_categories': top_next_cat,
        'action_prob_next5': action_prob,
    }


# ═══════════════════════════════════════════════════════════════
# NEW ANALYSES  (v0.2.0)
# ═══════════════════════════════════════════════════════════════

def analysis_hover_conversion(events: list[Event], window: int = 10) -> dict:
    """
    For every hover event, measure P(action in next WINDOW events).
    Compare to baseline P(action in any random WINDOW).

    Reveals: does hovering actually predict engagement, or is it cheap?
    """
    action_union = ACTION_CATS | {'react'}
    filt = [e for e in events if e.category in (USER_BEHAVIOR_CATS | {'ad'})]
    if len(filt) < 30:
        return {'available': False, 'reason': 'Not enough events'}
    hover_idxs = [i for i, e in enumerate(filt) if e.category == 'hover']
    if len(hover_idxs) < 5:
        return {'available': False, 'reason': 'Too few hover events'}

    # P(action within WINDOW of a hover)
    n_hover_with_action = 0
    latencies = []  # events between hover and the next action (if any)
    for i in hover_idxs:
        for j in range(1, window + 1):
            k = i + j
            if k >= len(filt):
                break
            if filt[k].category in action_union:
                n_hover_with_action += 1
                latencies.append(j)
                break

    p_hover_conv = n_hover_with_action / len(hover_idxs)

    # Baseline: P(action within WINDOW of a RANDOM event)
    rng = random.Random(314159)
    n_samples = min(len(hover_idxs) * 20, len(filt) - 1)
    random_idxs = [rng.randrange(len(filt)) for _ in range(n_samples)]
    n_rand_with_action = 0
    for i in random_idxs:
        for j in range(1, window + 1):
            k = i + j
            if k >= len(filt):
                break
            if filt[k].category in action_union:
                n_rand_with_action += 1
                break
    p_rand_conv = n_rand_with_action / max(1, n_samples)

    lift = (p_hover_conv / p_rand_conv) if p_rand_conv > 0 else 0
    median_latency = statistics.median(latencies) if latencies else None

    return {
        'available': True,
        'n_hovers': len(hover_idxs),
        'n_hover_with_action': n_hover_with_action,
        'p_hover_converts': p_hover_conv,
        'p_baseline_converts': p_rand_conv,
        'lift': lift,
        'median_latency_events': median_latency,
        'window': window,
    }


def analysis_ad_dose_response(events: list[Event], max_k: int = 30) -> dict:
    """
    For k=1..max_k, estimate P(action at offset k | ad_expose at 0)
    minus baseline P(action at any offset k).

    Reveals whether ads measurably shift your next-k-events behavior.
    """
    action_union = ACTION_CATS | {'react'}
    # Use full behavior + ad sequence for context
    filt = [e for e in events if e.category in (USER_BEHAVIOR_CATS | {'ad'})]
    if len(filt) < 50:
        return {'available': False, 'reason': 'Not enough events'}
    ad_idxs = [i for i, e in enumerate(filt) if e.category == 'ad']
    if len(ad_idxs) < 3:
        return {'available': False, 'reason': 'Too few ad events'}

    # P(action at offset k | ad at 0)
    p_action_after_ad = [0.0] * (max_k + 1)
    counts_after_ad = [0] * (max_k + 1)
    for i in ad_idxs:
        for k in range(1, max_k + 1):
            j = i + k
            if j >= len(filt):
                break
            counts_after_ad[k] += 1
            if filt[j].category in action_union:
                p_action_after_ad[k] += 1
    for k in range(1, max_k + 1):
        if counts_after_ad[k] > 0:
            p_action_after_ad[k] /= counts_after_ad[k]

    # Baseline: P(action at offset k from a random event)
    rng = random.Random(271828)
    n_samples = min(max(100, len(ad_idxs) * 10), len(filt))
    random_idxs = [rng.randrange(len(filt)) for _ in range(n_samples)]
    p_action_random = [0.0] * (max_k + 1)
    counts_random = [0] * (max_k + 1)
    for i in random_idxs:
        for k in range(1, max_k + 1):
            j = i + k
            if j >= len(filt):
                break
            counts_random[k] += 1
            if filt[j].category in action_union:
                p_action_random[k] += 1
    for k in range(1, max_k + 1):
        if counts_random[k] > 0:
            p_action_random[k] /= counts_random[k]

    # Cumulative P(action within k) for both
    cum_after = []
    cum_rand = []
    cum_a = 1.0
    cum_r = 1.0
    for k in range(1, max_k + 1):
        cum_a *= (1 - p_action_after_ad[k])
        cum_r *= (1 - p_action_random[k])
        cum_after.append(1 - cum_a)
        cum_rand.append(1 - cum_r)

    return {
        'available': True,
        'n_ads': len(ad_idxs),
        'n_random_samples': n_samples,
        'max_k': max_k,
        'p_action_after_ad': p_action_after_ad,
        'p_action_random': p_action_random,
        'cum_after_ad': cum_after,
        'cum_baseline': cum_rand,
    }


def analysis_rev_boundaries(events: list[Event]) -> dict:
    """
    A bundle revision (__rev) change inside a session is Facebook shipping code
    to you mid-scroll. Compare behavior before vs after each rev boundary.
    """
    if len(events) < 30:
        return {'available': False, 'reason': 'Not enough events'}
    # Identify rev boundaries in event order
    boundaries = []  # list of (index, old_rev, new_rev)
    prev_rev = events[0].rev
    for i, e in enumerate(events):
        if e.rev and e.rev != prev_rev:
            boundaries.append((i, prev_rev, e.rev))
            prev_rev = e.rev
    if not boundaries:
        return {'available': False, 'reason': 'No bundle revisions mid-session'}

    # For each boundary, compare the 50 events before vs 50 events after
    window = 50
    comparisons = []
    for idx, old_rev, new_rev in boundaries:
        before = events[max(0, idx - window):idx]
        after = events[idx:min(len(events), idx + window)]
        if len(before) < 10 or len(after) < 10:
            continue
        cat_before = Counter(e.category for e in before if e.category in USER_BEHAVIOR_CATS)
        cat_after = Counter(e.category for e in after if e.category in USER_BEHAVIOR_CATS)
        total_b = sum(cat_before.values()) or 1
        total_a = sum(cat_after.values()) or 1
        deltas = {}
        for cat in USER_BEHAVIOR_CATS:
            pb = cat_before[cat] / total_b
            pa = cat_after[cat] / total_a
            deltas[cat] = pa - pb  # change in share
        # Bucket size / rhythm change
        if before and after:
            rate_before = len(before) / max(1, before[-1].timestamp - before[0].timestamp)
            rate_after = len(after) / max(1, after[-1].timestamp - after[0].timestamp)
        else:
            rate_before = rate_after = 0
        comparisons.append({
            'idx': idx,
            'timestamp': events[idx].timestamp,
            'old_rev': old_rev,
            'new_rev': new_rev,
            'deltas': deltas,
            'rate_before': rate_before,
            'rate_after': rate_after,
            'n_before': len(before),
            'n_after': len(after),
        })
    if not comparisons:
        return {'available': False, 'reason': 'Boundaries present but surrounding context too small'}
    return {
        'available': True,
        'n_boundaries': len(comparisons),
        'comparisons': comparisons,
    }


def analysis_survival(events: list[Event], max_t: float = 120.0) -> dict:
    """
    Kaplan–Meier survival curve: P(no action yet by elapsed time t).
    At each view/hover event, measure time until the next action.
    If the session ends first → right-censored.
    """
    action_union = ACTION_CATS | {'react'}
    # Index sequence of user-behavior events
    filt = [e for e in events if e.category in USER_BEHAVIOR_CATS]
    if len(filt) < 30:
        return {'available': False, 'reason': 'Not enough events'}

    # For each non-action event, measure time (seconds) to next action
    durations = []  # (elapsed_seconds, event_was_action)
    for i, e in enumerate(filt):
        if e.category in action_union:
            continue
        # Look forward for the next action
        found = False
        for j in range(i + 1, len(filt)):
            if filt[j].category in action_union:
                dt = filt[j].timestamp - e.timestamp
                if dt >= 0 and dt <= max_t * 4:  # clip wildly long gaps
                    durations.append((dt, True))
                found = True
                break
        if not found:
            dt = filt[-1].timestamp - e.timestamp
            if dt > 0:
                durations.append((dt, False))

    if not durations:
        return {'available': False, 'reason': 'No observable times'}

    # Kaplan-Meier: at each unique event-time with event=True, update survival
    times = sorted(set(d for d, _ in durations))
    # Include t=0 for plotting
    survival_curve = []
    n_at_risk = len(durations)
    S = 1.0
    # Simple KM: sort events, then iterate
    sorted_events = sorted(durations, key=lambda x: x[0])
    idx = 0
    for t in times:
        if t > max_t:
            break
        d_t = sum(1 for dt, ev in sorted_events if dt == t and ev)
        n_t = sum(1 for dt, _ in sorted_events if dt >= t)
        if n_t > 0 and d_t > 0:
            S *= (1 - d_t / n_t)
        survival_curve.append((t, S))

    # Median survival time (time at which S(t) first drops below 0.5)
    median_t = None
    for t, s in survival_curve:
        if s <= 0.5:
            median_t = t
            break

    # Mean "dwell" time (only for non-censored)
    uncensored = [d for d, ev in durations if ev]
    mean_dwell = statistics.mean(uncensored) if uncensored else None

    return {
        'available': True,
        'n_durations': len(durations),
        'n_uncensored': len(uncensored),
        'survival_curve': survival_curve,
        'median_survival': median_t,
        'mean_dwell': mean_dwell,
        'max_t': max_t,
    }


def analysis_self_surveillance(events: list[Event]) -> dict:
    """
    Facebook's own telemetry — ScreenTimeLogger, TimeLimitsEnforcement,
    RecordProductUsage, UnifiedVideoSeenState, etc. Measures FB's sampling
    cadence of YOU, from inside your browser.
    """
    surv_events = [e for e in events if e.category == 'self_surv']
    notif_seen = [e for e in events if e.category == 'notif_seen']
    presence = [e for e in events if e.category == 'presence']
    if not surv_events and not presence:
        return {'available': False, 'reason': 'No FB self-telemetry in capture'}

    # Intervals between each kind
    def intervals(evs):
        ts = sorted(e.timestamp for e in evs)
        return [ts[i + 1] - ts[i] for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > 0]

    surv_iv = intervals(surv_events)
    pres_iv = intervals(presence)
    nseen_iv = intervals(notif_seen)

    # Top categories within self_surv
    surv_by_label = Counter(e.label for e in surv_events)

    # Behavior rate around self_surv events (is FB sampling more when you're active?)
    action_union = ACTION_CATS | {'react'}
    behavior_per_surv = []
    for e in surv_events:
        t = e.timestamp
        window = 30  # seconds
        n_before = sum(1 for f in events
                       if t - window <= f.timestamp < t
                       and f.category in USER_BEHAVIOR_CATS)
        behavior_per_surv.append(n_before)

    median_behavior_around_surv = statistics.median(behavior_per_surv) if behavior_per_surv else None

    return {
        'available': True,
        'n_self_surv': len(surv_events),
        'n_presence': len(presence),
        'n_notif_seen': len(notif_seen),
        'median_surv_interval_s': statistics.median(surv_iv) if surv_iv else None,
        'median_presence_interval_s': statistics.median(pres_iv) if pres_iv else None,
        'median_notif_seen_interval_s': statistics.median(nseen_iv) if nseen_iv else None,
        'top_surv_labels': dict(surv_by_label.most_common(6)),
        'median_behavior_around_surv': median_behavior_around_surv,
    }


def analysis_anomalies(events: list[Event], top_k: int = 10) -> dict:
    """
    Isolation-like anomaly scoring from five features per event:
      • time-since-previous (log-scale)
      • same-route-streak-length
      • category surprisal (-log p(cat | prev_cat)) via a Markov model
      • ccg deviation (encodes network weirdness)
      • latency deviation (if userscript v2 data present)

    Top-k highest scoring events are surfaced as "unusual moments."
    """
    if len(events) < 50:
        return {'available': False, 'reason': 'Not enough events'}
    filt = [e for e in events if e.category in USER_BEHAVIOR_CATS]
    if len(filt) < 50:
        return {'available': False, 'reason': 'Not enough behavior events'}

    # Pre-compute Markov cat→cat for surprisal
    c_trans: dict = defaultdict(Counter)
    for i in range(len(filt) - 1):
        c_trans[filt[i].category][filt[i + 1].category] += 1
    c_probs = {c: laplace_smooth(dict(v), alpha=1.0, vocab=set(filt[i].category for i in range(len(filt))))
               for c, v in c_trans.items()}

    # Compute per-event features
    scores = []
    streak = 1
    for i, e in enumerate(filt):
        if i == 0:
            dt = 0.0
        else:
            dt = e.timestamp - filt[i - 1].timestamp
        # streak
        if i > 0 and filt[i].route == filt[i - 1].route:
            streak += 1
        else:
            streak = 1
        # surprisal
        if i > 0:
            prev_cat = filt[i - 1].category
            p = c_probs.get(prev_cat, {}).get(e.category, 1e-6)
            surp = -math.log(max(p, 1e-6))
        else:
            surp = 0.0
        # ccg deviation: MODERATE/GOOD/BAD mapped to codes; change = anomaly
        score = 0.0
        # large gap is weird
        if dt > 0:
            score += math.log1p(dt) * 0.4
        score += surp
        if streak >= 20:
            score += (streak - 20) * 0.05
        if e.latency_ms > 1000:
            score += math.log(e.latency_ms / 1000) * 0.6
        scores.append((i, score))

    # Top-K by score
    scores.sort(key=lambda s: -s[1])
    top = scores[:top_k]
    anomalies = []
    for idx, sc in top:
        e = filt[idx]
        anomalies.append({
            'seq': e.seq,
            'timestamp': e.timestamp,
            'label': e.label,
            'route': e.route,
            'friendly': e.friendly,
            'score': sc,
        })
    return {
        'available': True,
        'n_events': len(filt),
        'anomalies': anomalies,
    }


def analysis_decoder_coverage(events: list[Event]) -> dict:
    """Self-reflective panel: how much of YOUR data did the decoder match?"""
    total_with_friendly = 0
    matched = 0
    by_cat = Counter()
    unmatched_names: Counter = Counter()
    for e in events:
        if e.friendly:
            total_with_friendly += 1
            if e.label in ('Performing action', 'Loading data', 'Unknown activity'):
                unmatched_names[e.friendly] += 1
            else:
                matched += 1
        by_cat[e.category] += 1
    total = len(events)
    return {
        'available': True,
        'total': total,
        'with_friendly': total_with_friendly,
        'matched': matched,
        'match_rate': matched / total_with_friendly if total_with_friendly else 0,
        'unmatched_top': unmatched_names.most_common(10),
        'n_unique_unmatched': len(unmatched_names),
        'by_category': dict(by_cat),
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
    # Stacked bars by category (user-behavior on bottom, ad/system on top)
    stack_order = ['view', 'hover', 'react', 'act', 'compose', 'msg', 'search', 'ad', 'nav', 'notif_seen', 'presence', 'self_surv']
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
            opacity = 0.85 if cat in USER_BEHAVIOR_CATS else 0.5
            parts.append(
                f'<rect x="{x:.1f}" y="{y_cursor:.1f}" width="{max(0.8, bw - 0.8):.1f}" height="{h:.1f}" '
                f'fill="{color}" opacity="{opacity}"/>'
            )
        # Burst marker
        if i in bursts:
            parts.append(
                f'<circle cx="{x + bw/2:.1f}" cy="{PAD + 8}" r="4" fill="#ff4fd8" opacity="0.9"/>'
            )

    # Axis labels
    parts.append(f'<text x="{PAD}" y="{H - PAD + 20}" class="label-sm">session start</text>')
    parts.append(f'<text x="{W - PAD}" y="{H - PAD + 20}" class="label-sm" text-anchor="end">session end</text>')
    parts.append(f'<text x="{PAD}" y="{PAD - 10}" class="label-sm" fill="#ff4fd8">● burst (MAD-z &gt; 3.5)</text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_hooks(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'

    lifts = data['category_lifts']
    p_values = data.get('p_values', {}) or {}
    # Sort by lift descending, exclude nav / self_surv / presence (they pollute)
    items = [(c, l) for c, l in lifts.items()
             if c not in ('nav', 'self_surv', 'presence', 'notif_seen')]
    items.sort(key=lambda kv: -kv[1])

    W = 780
    PAD_L = 130
    PAD_R = 100
    PAD_T = 40
    PAD_B = 30
    row_h = 26
    H = PAD_T + PAD_B + row_h * len(items)
    max_lift = max(max(v for _, v in items), 2.0)

    parts = [svg_tag(W, H)]
    # 1.0 reference line
    zero_x = PAD_L + (W - PAD_L - PAD_R) * (1.0 / max_lift)
    parts.append(f'<line x1="{zero_x:.1f}" y1="{PAD_T - 5}" x2="{zero_x:.1f}" y2="{H - PAD_B + 5}" class="axis-mark"/>')
    parts.append(f'<text x="{zero_x:.1f}" y="{PAD_T - 10}" class="label-xs" text-anchor="middle" fill="#5a8ca0">baseline 1×</text>')

    for i, (cat, lift) in enumerate(items):
        y = PAD_T + i * row_h + row_h / 2
        bar_w = (W - PAD_L - PAD_R) * min(lift, max_lift) / max_lift
        color = CATEGORY_COLORS.get(cat, '#888')
        label = CATEGORY_LABELS.get(cat, cat)
        parts.append(f'<text x="{PAD_L - 10}" y="{y + 4}" class="label-sm" text-anchor="end" fill="{color}">{label}</text>')
        parts.append(f'<rect x="{PAD_L}" y="{y - row_h * 0.30:.1f}" width="{bar_w:.1f}" height="{row_h * 0.60:.1f}" fill="{color}" opacity="0.75"/>')
        # Lift value + significance stars (p<0.01 ***, p<0.05 **, p<0.10 *)
        pv = p_values.get(cat)
        stars = ''
        if pv is not None:
            if pv < 0.01: stars = ' ***'
            elif pv < 0.05: stars = ' **'
            elif pv < 0.10: stars = ' *'
        parts.append(
            f'<text x="{PAD_L + bar_w + 6}" y="{y + 4}" class="label-sm" fill="{color}">'
            f'{lift:.2f}×{stars}</text>'
        )
        if pv is not None and pv < 1.0:
            parts.append(
                f'<text x="{W - 6}" y="{y + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">'
                f'p={pv:.3f}</text>'
            )

    parts.append(f'<text x="{PAD_L}" y="{H - 6}" class="label-xs" fill="#5a8ca0">'
                 f'*** p&lt;0.01 &nbsp; ** p&lt;0.05 &nbsp; * p&lt;0.10 &nbsp; '
                 f'(permutation test, {data.get("n_perms",500)} perms)</text>')

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
    stack_order = ['view', 'hover', 'react', 'act', 'compose', 'msg', 'search', 'ad', 'nav', 'notif_seen', 'presence', 'self_surv']
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
# NEW RENDERERS (v0.2.0)
# ═══════════════════════════════════════════════════════════════

def render_hover_conversion(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    W, H = 720, 240
    p_h = data['p_hover_converts']
    p_b = data['p_baseline_converts']
    lift = data['lift']
    parts = [svg_tag(W, H)]
    # Two bars — hover conversion vs baseline conversion
    PAD = 40
    bar_w = 260
    for i, (label, p, color) in enumerate([
        ('after a hover', p_h, '#c3f0ff'),
        ('random event (baseline)', p_b, '#5a8ca0'),
    ]):
        y = PAD + 20 + i * 80
        parts.append(f'<text x="{PAD}" y="{y}" class="label-sm" fill="{color}">{label}</text>')
        parts.append(f'<rect x="{PAD}" y="{y + 14}" width="{bar_w}" height="24" fill="#0a2030" stroke="#1a3848"/>')
        fill_w = bar_w * min(1.0, p)
        parts.append(f'<rect x="{PAD}" y="{y + 14}" width="{fill_w:.1f}" height="24" fill="{color}" opacity="0.85"/>')
        parts.append(f'<text x="{PAD + bar_w + 12}" y="{y + 32}" class="label-sm" fill="{color}">{p*100:.1f}%</text>')
    # Big lift number on right
    parts.append(f'<text x="{W - 200}" y="{H - 20}" class="label-xs" fill="#5a8ca0">conversion lift</text>')
    lcol = '#ff4fd8' if lift > 1.2 else ('#fff275' if lift > 1.0 else '#5a8ca0')
    parts.append(f'<text x="{W - 200}" y="{H - 45}" style="fill:{lcol};font-family:\'Major Mono Display\',monospace;font-size:42px;letter-spacing:0.05em">{lift:.2f}×</text>')
    ml = data.get('median_latency_events')
    if ml:
        parts.append(f'<text x="{W - 200}" y="{60}" class="label-xs" fill="#5a8ca0">median delay: <tspan fill="#00ffd1">{int(ml)} events</tspan></text>')
    parts.append('</svg>')
    return ''.join(parts)


def render_ad_dose_response(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    W, H = 900, 320
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 60, 40, 50
    max_k = data['max_k']
    cum_a = data['cum_after_ad']
    cum_b = data['cum_baseline']
    parts = [svg_tag(W, H)]
    parts.append(svg_grid(W, H, xs=max_k // 3, ys=5, pad=PAD_L))
    max_y = max(max(cum_a + cum_b, default=0), 0.05) * 1.1

    def x_for(k): return PAD_L + (W - PAD_L - PAD_R) * (k - 1) / max(1, max_k - 1)
    def y_for(v): return H - PAD_B - (H - PAD_T - PAD_B) * (v / max_y)

    # Baseline (grey) first
    pts_b = ' '.join(f'{x_for(k+1):.1f},{y_for(cum_b[k]):.1f}' for k in range(len(cum_b)))
    parts.append(f'<polyline points="{pts_b}" fill="none" stroke="#5a8ca0" stroke-width="1.6" stroke-dasharray="4,3"/>')
    # After-ad (orange)
    pts_a = ' '.join(f'{x_for(k+1):.1f},{y_for(cum_a[k]):.1f}' for k in range(len(cum_a)))
    parts.append(f'<polyline points="{pts_a}" fill="none" stroke="#ff9f40" stroke-width="2.4"/>')
    # Fill between (gap visible)
    area = (
        f'{PAD_L},{y_for(0)} '
        + pts_a +
        f' {PAD_L + (W - PAD_L - PAD_R)},{y_for(0)}'
    )
    parts.append(f'<polygon points="{area}" fill="#ff9f40" opacity="0.05"/>')

    # Axis labels
    for k in (1, 5, 10, 15, 20, 25, 30):
        if k <= max_k:
            parts.append(f'<text x="{x_for(k):.1f}" y="{H - PAD_B + 18}" class="label-sm" text-anchor="middle">k={k}</text>')
    parts.append(f'<text x="{PAD_L - 6}" y="{y_for(0) + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">0%</text>')
    parts.append(f'<text x="{PAD_L - 6}" y="{y_for(max_y) + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">{max_y*100:.0f}%</text>')
    parts.append(f'<text x="{W/2}" y="{H - 8}" class="label-xs" text-anchor="middle" fill="#5a8ca0">events after ad exposure</text>')

    # Legend
    parts.append(f'<line x1="{W - 260}" y1="{PAD_T + 20}" x2="{W - 240}" y2="{PAD_T + 20}" stroke="#ff9f40" stroke-width="2.4"/>')
    parts.append(f'<text x="{W - 234}" y="{PAD_T + 24}" class="label-sm" fill="#ff9f40">P(action | ad at 0)</text>')
    parts.append(f'<line x1="{W - 260}" y1="{PAD_T + 40}" x2="{W - 240}" y2="{PAD_T + 40}" stroke="#5a8ca0" stroke-width="1.6" stroke-dasharray="4,3"/>')
    parts.append(f'<text x="{W - 234}" y="{PAD_T + 44}" class="label-sm" fill="#5a8ca0">baseline P(action)</text>')

    parts.append(f'<text x="{PAD_L}" y="{PAD_T - 15}" class="label-xs" fill="#5a8ca0">cumulative prob (K-M style)</text>')
    parts.append('</svg>')
    return ''.join(parts)


def render_rev_boundaries(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    comps = data['comparisons']
    W = 820
    row_h = 130
    H = 40 + row_h * len(comps)
    parts = [svg_tag(W, H)]

    for i, c in enumerate(comps):
        y0 = 30 + i * row_h
        # Rev change header
        parts.append(f'<text x="20" y="{y0}" class="label-sm" fill="#ff4fd8">✂ rev {c["old_rev"]} → {c["new_rev"]}</text>')
        ts = datetime.fromtimestamp(c['timestamp'], tz=timezone.utc).strftime('%H:%M UTC')
        parts.append(f'<text x="20" y="{y0 + 16}" class="label-xs" fill="#5a8ca0">at event {c["idx"]} · {ts}</text>')

        # Mini horizontal delta bars, one per category
        cats = ['view', 'hover', 'react', 'act', 'msg', 'compose', 'search', 'ad']
        x0 = 320
        bar_w = 180
        bar_h = 10
        row_y = y0 - 4
        max_delta = max([abs(c['deltas'].get(cat, 0)) for cat in cats] + [0.05])
        for j, cat in enumerate(cats):
            yc = row_y + j * 12
            d = c['deltas'].get(cat, 0)
            color = CATEGORY_COLORS[cat]
            parts.append(f'<text x="{x0 - 6}" y="{yc + 8}" class="label-xs" text-anchor="end" fill="{color}">{cat}</text>')
            mid = x0 + bar_w / 2
            parts.append(f'<line x1="{mid}" y1="{yc}" x2="{mid}" y2="{yc + bar_h}" stroke="#1a3848"/>')
            w = (bar_w / 2) * (abs(d) / max_delta)
            if d >= 0:
                parts.append(f'<rect x="{mid}" y="{yc}" width="{w:.1f}" height="{bar_h}" fill="{color}" opacity="0.85"/>')
            else:
                parts.append(f'<rect x="{mid - w:.1f}" y="{yc}" width="{w:.1f}" height="{bar_h}" fill="{color}" opacity="0.85"/>')
            parts.append(f'<text x="{x0 + bar_w + 8}" y="{yc + 8}" class="label-xs" fill="{color}">{d*100:+.1f}pp</text>')

        # Rate change
        rb, ra = c['rate_before'], c['rate_after']
        rate_delta = ((ra - rb) / rb * 100) if rb > 0 else 0
        parts.append(f'<text x="{W - 260}" y="{y0}" class="label-xs" fill="#5a8ca0">rate before</text>')
        parts.append(f'<text x="{W - 260}" y="{y0 + 14}" class="label-sm" fill="#7ad7ff">{rb*60:.1f}/min</text>')
        parts.append(f'<text x="{W - 140}" y="{y0}" class="label-xs" fill="#5a8ca0">rate after</text>')
        parts.append(f'<text x="{W - 140}" y="{y0 + 14}" class="label-sm" fill="#7ad7ff">{ra*60:.1f}/min ({rate_delta:+.0f}%)</text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_survival(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    W, H = 900, 320
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 80, 40, 50
    curve = data['survival_curve']
    if not curve:
        return '<div class="empty">no observable dwell times</div>'
    max_t = data['max_t']
    parts = [svg_tag(W, H)]
    parts.append(svg_grid(W, H, xs=6, ys=4, pad=PAD_L))

    def x_for(t): return PAD_L + (W - PAD_L - PAD_R) * (t / max_t)
    def y_for(s): return H - PAD_B - (H - PAD_T - PAD_B) * s

    # Step-function
    pts = [(0, 1.0)]
    for t, s in curve:
        if t > max_t: break
        pts.append((t, pts[-1][1]))
        pts.append((t, s))
    pts.append((max_t, pts[-1][1]))
    poly = ' '.join(f'{x_for(t):.1f},{y_for(s):.1f}' for t, s in pts)
    parts.append(f'<polyline points="{poly}" fill="none" stroke="#ff4fd8" stroke-width="2.2"/>')
    # Under-curve fill (how much "you were engaged")
    area = f'{x_for(0)},{y_for(0)} ' + poly + f' {x_for(max_t)},{y_for(0)}'
    parts.append(f'<polygon points="{area}" fill="#ff4fd8" opacity="0.08"/>')

    # 50% reference line
    parts.append(f'<line x1="{PAD_L}" y1="{y_for(0.5)}" x2="{W - PAD_R}" y2="{y_for(0.5)}" class="axis-mark"/>')
    parts.append(f'<text x="{W - PAD_R + 6}" y="{y_for(0.5) + 4}" class="label-xs" fill="#ff4fd8">50%</text>')

    # Median marker
    mt = data.get('median_survival')
    if mt:
        parts.append(f'<line x1="{x_for(mt)}" y1="{PAD_T}" x2="{x_for(mt)}" y2="{y_for(0)}" stroke="#00ffd1" stroke-dasharray="3,3" opacity="0.7"/>')
        parts.append(f'<text x="{x_for(mt)}" y="{PAD_T - 8}" class="label-sm" text-anchor="middle" fill="#00ffd1">median {mt:.1f}s</text>')

    # X labels
    for t in (0, 15, 30, 60, 120):
        if t <= max_t:
            parts.append(f'<text x="{x_for(t):.1f}" y="{H - PAD_B + 18}" class="label-sm" text-anchor="middle">{t}s</text>')
    parts.append(f'<text x="{W/2}" y="{H - 8}" class="label-xs" text-anchor="middle" fill="#5a8ca0">seconds from a viewing event to the next action</text>')
    parts.append(f'<text x="{PAD_L - 6}" y="{y_for(1) + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">100%</text>')
    parts.append(f'<text x="{PAD_L - 6}" y="{y_for(0) + 4}" class="label-xs" text-anchor="end" fill="#5a8ca0">0%</text>')
    parts.append('</svg>')
    return ''.join(parts)


def render_self_surveillance(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    W, H = 820, 260
    PAD = 40
    parts = [svg_tag(W, H)]

    # Four stat cards inline
    cards = [
        ('screen-time logs', data['n_self_surv'], data.get('median_surv_interval_s'), 's between'),
        ('presence pings',   data['n_presence'], data.get('median_presence_interval_s'), 's between'),
        ('notif clears',     data['n_notif_seen'], data.get('median_notif_seen_interval_s'), 's between'),
        ('behavior window',  data.get('median_behavior_around_surv'), None, 'events in 30s'),
    ]
    cw = (W - 2 * PAD) / 4
    for i, (label, n, iv, unit) in enumerate(cards):
        x = PAD + i * cw
        parts.append(f'<rect x="{x + 6}" y="{PAD}" width="{cw - 12}" height="140" fill="#0a2030" stroke="#8c5a9a" stroke-width="1" opacity="0.5"/>')
        parts.append(f'<text x="{x + cw/2}" y="{PAD + 30}" class="label-xs" text-anchor="middle" fill="#8c5a9a">{label}</text>')
        val = '—' if n is None else (f'{n:.1f}' if isinstance(n, float) else f'{n}')
        parts.append(f'<text x="{x + cw/2}" y="{PAD + 80}" style="fill:#8c5a9a;font-family:\'Major Mono Display\',monospace;font-size:34px;letter-spacing:0.05em" text-anchor="middle">{val}</text>')
        if iv is not None:
            parts.append(f'<text x="{x + cw/2}" y="{PAD + 110}" class="label-xs" text-anchor="middle" fill="#5a8ca0">~{iv:.0f} {unit}</text>')
        else:
            parts.append(f'<text x="{x + cw/2}" y="{PAD + 110}" class="label-xs" text-anchor="middle" fill="#5a8ca0">{unit}</text>')

    # Top self-surv labels
    y = PAD + 170
    top_labels = list(data.get('top_surv_labels', {}).items())[:4]
    if top_labels:
        parts.append(f'<text x="{PAD}" y="{y}" class="label-xs" fill="#8c5a9a">FB\'s top telemetry calls on you:</text>')
        for i, (lbl, n) in enumerate(top_labels):
            parts.append(f'<text x="{PAD}" y="{y + 20 + i * 14}" class="label-sm" fill="#5a8ca0">{html_lib.escape(str(lbl))} <tspan fill="#c3a6d6">· {n}×</tspan></text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_anomalies(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    W = 820
    row_h = 30
    anoms = data['anomalies']
    H = 40 + row_h * max(1, len(anoms))
    parts = [svg_tag(W, H)]
    # Header
    parts.append(f'<text x="20" y="20" class="label-xs" fill="#5a8ca0">seq · score · route · event</text>')
    max_score = max((a['score'] for a in anoms), default=1) or 1
    for i, a in enumerate(anoms):
        y = 40 + i * row_h
        route_lbl = ROUTE_LABELS.get(a['route'], a['route'].replace('comet.fbweb.', '')[:24])
        color = ROUTE_COLORS.get(a['route'], '#888')
        bar_w = 180 * (a['score'] / max_score)
        parts.append(f'<text x="20" y="{y + 14}" class="label-sm" fill="#7ad7ff">#{a["seq"]}</text>')
        parts.append(f'<rect x="80" y="{y + 4}" width="{bar_w:.1f}" height="16" fill="#ff4fd8" opacity="0.7"/>')
        parts.append(f'<text x="{80 + bar_w + 8}" y="{y + 16}" class="label-xs" fill="#5a8ca0">{a["score"]:.2f}</text>')
        parts.append(f'<text x="340" y="{y + 14}" class="label-sm" fill="{color}">{route_lbl}</text>')
        lbl = a.get('friendly') or a['label']
        parts.append(f'<text x="480" y="{y + 14}" class="label-sm" fill="#e4f3fb">{html_lib.escape(str(lbl))[:40]}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def render_decoder_coverage(data: dict) -> str:
    if not data.get('available'):
        return f'<div class="empty">{data.get("reason","No data")}</div>'
    W, H = 820, 280
    PAD = 40
    parts = [svg_tag(W, H)]

    rate = data['match_rate']
    # Coverage ring
    CX, CY, R = 140, 140, 80
    circ = 2 * math.pi * R
    dash = circ * rate
    parts.append(f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="#1a3848" stroke-width="16"/>')
    parts.append(
        f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="#00ffd1" stroke-width="16" '
        f'stroke-dasharray="{dash:.1f},{circ:.1f}" transform="rotate(-90 {CX} {CY})"/>'
    )
    parts.append(f'<text x="{CX}" y="{CY - 4}" style="fill:#00ffd1;font-family:\'Major Mono Display\',monospace;font-size:32px" text-anchor="middle">{rate*100:.0f}%</text>')
    parts.append(f'<text x="{CX}" y="{CY + 22}" class="label-xs" text-anchor="middle" fill="#5a8ca0">decoder coverage</text>')

    # Stats block
    x0 = 310
    parts.append(f'<text x="{x0}" y="70" class="label-sm" fill="#7ad7ff">total events: <tspan fill="#00ffd1">{data["total"]}</tspan></text>')
    parts.append(f'<text x="{x0}" y="92" class="label-sm" fill="#7ad7ff">with friendly_name: <tspan fill="#00ffd1">{data["with_friendly"]}</tspan></text>')
    parts.append(f'<text x="{x0}" y="114" class="label-sm" fill="#7ad7ff">matched: <tspan fill="#00ffd1">{data["matched"]}</tspan></text>')
    parts.append(f'<text x="{x0}" y="136" class="label-sm" fill="#7ad7ff">unique unmatched: <tspan fill="#ff4fd8">{data["n_unique_unmatched"]}</tspan></text>')

    # Top unmatched names
    parts.append(f'<text x="{x0}" y="170" class="label-xs" fill="#5a8ca0">top unmatched friendly_names (feed these to reflex_discover):</text>')
    for i, (name, cnt) in enumerate(data.get('unmatched_top', [])[:6]):
        y = 186 + i * 14
        parts.append(f'<text x="{x0}" y="{y}" class="label-sm" fill="#ff4fd8">{cnt}×</text>')
        parts.append(f'<text x="{x0 + 50}" y="{y}" class="label-sm" fill="#b8d4e0">{html_lib.escape(name[:60])}</text>')
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

  .summary-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; margin-bottom: 48px; }}
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

  @media (max-width: 900px) {{
    .summary-grid {{ grid-template-columns: repeat(3, 1fr); }}
  }}
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
  <div class="stat-card"><span class="v">{n_hovers}</span><div class="l">hover intents</div></div>
  <div class="stat-card"><span class="v">{n_ads}</span><div class="l">ad impressions</div></div>
  <div class="stat-card"><span class="v">{n_segments}</span><div class="l">session segments</div></div>
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
    # Analyses — classic six
    a_response = analysis_action_response(events)
    a_trans    = analysis_transitions(events)
    a_rhythm   = analysis_rhythm(events)
    a_hooks    = analysis_hooks(events)
    a_diurnal  = analysis_diurnal(events)
    a_predict  = analysis_predictions(events)
    # Analyses — v0.2.0 additions
    a_coverage = analysis_decoder_coverage(events)
    a_hover    = analysis_hover_conversion(events)
    a_ads      = analysis_ad_dose_response(events)
    a_rev      = analysis_rev_boundaries(events)
    a_surv     = analysis_survival(events)
    a_self     = analysis_self_surveillance(events)
    a_anom     = analysis_anomalies(events)

    n_events = len(events)
    n_actions = sum(1 for e in events if e.category in ACTION_CATS | {'react'})
    n_surfaces = len(set(e.route for e in events))
    n_segments = len(set(e.segment_id for e in events)) if events else 0
    n_hovers = sum(1 for e in events if e.category == 'hover')
    n_ads = sum(1 for e in events if e.category == 'ad')
    if events:
        duration = max(e.timestamp for e in events) - min(e.timestamp for e in events)
    else:
        duration = 0

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
                f"a MAD-based threshold (modified z-score &gt; 3.5 — robust to sparse sessions).</p>"
                f"<p>Your session carries a dominant rhythm with a period of roughly "
                f"<em>{bp_min:.1f} minutes</em> — attention oscillates at that rate (Welch periodogram peak).</p>"
            )
        else:
            findings_3 = (
                f"<p>Detected <em>{n_bursts} {burst_word}</em> (MAD-based threshold).</p>"
                f"<p>No periodic rhythm above the noise floor — your session is arrhythmic, "
                f"driven by external triggers rather than internal cycles.</p>"
            )
    sections_html.append(section(
        '03', 'session rhythm',
        "Activity density over time, bucketed by minute, stacked by category. "
        "Pink dots mark <em>burst moments</em> — buckets where activity exceeds the session's MAD-based threshold "
        "(modified z-score &gt; 3.5, robust to sparse sessions). The dominant period is recovered via a Welch periodogram, "
        "not a greedy local-max search. System categories (<em>presence</em>, <em>self_surv</em>, <em>nav</em>) are rendered "
        "faintly so they don't drown out your own behavior.",
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
        cv_mean = a_predict.get('cv_route_mean', acc)
        cv_std = a_predict.get('cv_route_std', 0)
        cv_folds = a_predict.get('cv_folds', 0)
        findings_6 = (
            f"<p>A Laplace-smoothed Markov model predicts the next surface with <em>{acc*100:.1f}%</em> accuracy "
            f"on the held-out 20% — <em>{lift:.2f}×</em> better than always-mode baseline.</p>"
            f"<p>Over {cv_folds}-fold time-series CV the model generalises at "
            f"<em>{cv_mean*100:.1f}% ± {cv_std*100:.1f}%</em>. Spread between folds tells you how stable "
            f"your behavior is across the session.</p>"
            f"<p>From where you left off, the most likely next move is <em>{top_label}</em> ({top_p*100:.0f}% chance).</p>"
        )
    sections_html.append(section(
        '06', 'prediction engine',
        "Reflex splits your session 80/20, trains a Laplace-smoothed Markov model on the earlier chunk, and predicts "
        "each next event in the later chunk. The <em>time-series k-fold CV</em> underneath (5 folds over temporal "
        "segments) catches distribution shift a single 80/20 split misses. The crystal ball applies the fully-trained "
        "model to your <em>very last</em> event: if you kept going right now, what would you probably do?",
        render_predictions(a_predict), findings_6,
        anchor='predictions',
    ))

    # ─── 07 — HOVER CONVERSION ───
    findings_7 = None
    if a_hover['available']:
        lift = a_hover['lift']
        ml = a_hover.get('median_latency_events')
        latency_phrase = f' within ~{int(ml)} events' if ml else ''
        if lift > 1.15:
            findings_7 = (
                f"<p>A hover is followed by an action {a_hover['p_hover_converts']*100:.1f}% of the time{latency_phrase} — "
                f"<em>{lift:.2f}×</em> the baseline rate ({a_hover['p_baseline_converts']*100:.1f}%).</p>"
                f"<p>The mouseover is a proto-commitment. The hand has decided before the click.</p>"
            )
        elif lift > 0.9:
            findings_7 = (
                f"<p>Hovers convert at roughly baseline rate ({lift:.2f}×). Your mouseovers are idle, not predictive.</p>"
            )
        else:
            findings_7 = (
                f"<p>Hovers convert at {lift:.2f}× baseline — actually <em>below</em> chance. "
                f"Your hover pattern is exploration, not selection.</p>"
            )
    sections_html.append(section(
        '07', 'hover — action conversion',
        "A mouse hover fires a Hovercard request before any click. This panel measures P(action within 10 events | hover at 0) "
        "against a random-event baseline. High lift means your hovers are fire-ahead signals — the algorithm, and Reflex, "
        "could predict your taps one intention ahead of them.",
        render_hover_conversion(a_hover), findings_7, anchor='hover',
    ))

    # ─── 08 — AD DOSE-RESPONSE ───
    findings_8 = None
    if a_ads['available']:
        # Compare cumulative gap at k=10
        ca = a_ads['cum_after_ad'][9] if len(a_ads['cum_after_ad']) >= 10 else a_ads['cum_after_ad'][-1]
        cb = a_ads['cum_baseline'][9] if len(a_ads['cum_baseline']) >= 10 else a_ads['cum_baseline'][-1]
        delta = ca - cb
        direction = 'above' if delta > 0.02 else ('below' if delta < -0.02 else 'at')
        findings_8 = (
            f"<p>After {a_ads['n_ads']} ad pre-fetch events, the cumulative probability of you "
            f"taking an action in the next 10 events is <em>{ca*100:.1f}%</em>, "
            f"<em>{direction}</em> baseline ({cb*100:.1f}%) by {delta*100:+.1f}pp.</p>"
            f"<p>The orange curve above the dashed line means ads measurably move your needle. "
            f"Below the line means they didn't move you — or they muted you.</p>"
        )
    sections_html.append(section(
        '08', 'ad dose — response',
        "Every <em>InstreamAds</em> / <em>AdsHalo</em> pre-fetch marks an ad reaching your viewport. This panel plots "
        "P(action at offset k | ad at 0) as a Kaplan-Meier-style cumulative, against a random-event baseline. "
        "The gap between the curves is the measurable behavioral effect of ad exposure, <em>on you</em>, "
        "with no API access, no survey, no panel — just your own request stream.",
        render_ad_dose_response(a_ads), findings_8, anchor='ads',
    ))

    # ─── 09 — REV BOUNDARIES (free A/B tests) ───
    findings_9 = None
    if a_rev['available']:
        comps = a_rev['comparisons']
        # Summary: average absolute delta across all boundaries
        if comps:
            all_deltas = [abs(d) for c in comps for d in c['deltas'].values()]
            mean_abs = statistics.mean(all_deltas) if all_deltas else 0
            findings_9 = (
                f"<p>Facebook shipped <em>{len(comps)} bundle revision{'s' if len(comps) != 1 else ''}</em> "
                f"during your session. Each is a free, involuntary A/B test.</p>"
                f"<p>Average absolute category-share shift across the {len(comps)} boundaries: "
                f"<em>{mean_abs*100:.1f}pp</em>. Anything &gt; 2pp suggests the deploy changed <em>something</em> in how you were served — "
                f"or how you responded.</p>"
            )
    sections_html.append(section(
        '09', 'revision boundaries — free a/b tests',
        "A <em>__rev</em> change mid-session is Facebook shipping new code to you mid-scroll. Reflex catches each "
        "boundary, compares the 50 events before and after (category mix, request rate), and shows the delta. "
        "Over days or weeks, these are the richest natural experiments available to anyone who isn't at Meta.",
        render_rev_boundaries(a_rev), findings_9, anchor='revs',
    ))

    # ─── 10 — SURVIVAL (time to next action) ───
    findings_10 = None
    if a_surv['available']:
        mt = a_surv.get('median_survival')
        mean = a_surv.get('mean_dwell')
        if mt is not None:
            findings_10 = (
                f"<p>Median time from a viewing event to your next action: <em>{mt:.1f} seconds</em>. "
                f"Half the time you act within that window. Half the time you hold out longer.</p>"
                f"<p>Mean dwell (for the non-censored sequences): {mean:.1f}s.</p>"
            )
        else:
            findings_10 = (
                f"<p>Survival curve stays above 50% across the observed window — "
                f"you rarely converted a passive view into an active tap in under 2 minutes.</p>"
            )
    sections_html.append(section(
        '10', 'time-to-action survival',
        "Kaplan-Meier-style survival: at each viewing event, the clock starts. P(you haven't acted yet) plotted against "
        "elapsed seconds. A sharp early drop = you're quick to engage. A long flat tail = you graze, you don't tap.",
        render_survival(a_surv), findings_10, anchor='survival',
    ))

    # ─── 11 — SELF-SURVEILLANCE ───
    findings_11 = None
    if a_self['available']:
        iv = a_self.get('median_surv_interval_s')
        if iv:
            findings_11 = (
                f"<p>Facebook logged its own telemetry about you "
                f"<em>{a_self['n_self_surv']} times</em> during this capture "
                f"(~every {iv:.0f}s). Your presence was pinged "
                f"<em>{a_self['n_presence']} times</em>.</p>"
                f"<p>This panel is the watcher watching the watcher. "
                f"The numbers shown are Facebook's sampling cadence of you, derived from your own browser.</p>"
            )
        else:
            findings_11 = (
                f"<p>Captured <em>{a_self['n_self_surv']}</em> self-surveillance telemetry events "
                f"from Facebook tracking your session internally.</p>"
            )
    sections_html.append(section(
        '11', 'self-surveillance meta-layer',
        "Facebook instruments itself too. <em>FBScreenTimeLogger_syncMutation</em>, "
        "<em>TimeLimitsEnforcementQuery</em>, <em>RecordProductUsageMutation</em>, <em>UnifiedVideoSeenStateMutation</em> — "
        "these fire while you browse. They're Facebook's telemetry of <em>you</em>, captured here from inside your "
        "own browser. This panel shows the cadence of their sampling — the ghost's own signal.",
        render_self_surveillance(a_self), findings_11, anchor='selfsurv',
    ))

    # ─── 12 — ANOMALIES ───
    findings_12 = None
    if a_anom['available']:
        top = a_anom['anomalies'][:3]
        if top:
            labels = ', '.join(f"#{a['seq']} ({a['label'][:28]})" for a in top)
            findings_12 = (
                f"<p>Top 3 unusual moments: <em>{labels}</em>.</p>"
                f"<p>These are sequence anomalies — large time gaps, unusual transitions, long streaks, "
                f"or latency spikes. If you remember any of them, it's because something actually happened.</p>"
            )
    sections_html.append(section(
        '12', 'anomaly surfacing',
        "Per-event anomaly score built from four features: log-gap to previous event, same-route streak length, "
        "category-transition surprisal, and latency deviation. The top 10 are surfaced — often these are the moments "
        "you'd actually remember from the session.",
        render_anomalies(a_anom), findings_12, anchor='anomalies',
    ))

    # ─── 13 — DECODER COVERAGE (self-diagnostic) ───
    findings_13 = None
    if a_coverage['available']:
        rate = a_coverage['match_rate']
        findings_13 = (
            f"<p>The v0.2.0 decoder matched <em>{rate*100:.1f}%</em> of your friendly_name'd traffic "
            f"({a_coverage['matched']}/{a_coverage['with_friendly']}). "
            f"<em>{a_coverage['n_unique_unmatched']}</em> unique names still fall through.</p>"
            f"<p>Run <code>python reflex_discover.py {{your.ndjson}}</code> to cluster unmatched names and grow "
            f"ACTIVITY_PATTERNS further.</p>"
        )
    sections_html.append(section(
        '13', 'decoder self-diagnostic',
        "How much of your capture did Reflex actually understand? The v0.2.0 decoder has 140+ patterns covering the "
        "full Comet / MAW / BizKit / LSPlatform surface; the ring shows match rate on YOUR data specifically. "
        "Top unmatched names are listed — feed them to <code>reflex_discover.py</code> and they become new patterns.",
        render_decoder_coverage(a_coverage), findings_13, anchor='coverage',
    ))

    # Assemble
    generated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    if events:
        t_min = min(e.timestamp for e in events)
        t_max = max(e.timestamp for e in events)
        t_from = datetime.fromtimestamp(t_min, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        t_to = datetime.fromtimestamp(t_max, tz=timezone.utc).strftime('%H:%M UTC')
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
        n_hovers=n_hovers,
        n_ads=n_ads,
        n_segments=n_segments,
        duration_human=humanize_duration(duration),
        version=VERSION,
        sections='\n'.join(sections_html),
    )


# ═══════════════════════════════════════════════════════════════
# CROSS-SESSION DIFF  (v0.2.0)
# "You on Tuesday vs you on Saturday."
# ═══════════════════════════════════════════════════════════════

def _summary_vector(events: list[Event]) -> dict:
    """Reduce a session to a comparable feature vector."""
    if not events:
        return {}
    total = len(events)
    cat_counts = Counter(e.category for e in events)
    cat_shares = {c: cat_counts[c] / total for c in CATEGORY_COLORS}
    route_counts = Counter(e.route for e in events)
    top_routes = dict(route_counts.most_common(8))
    duration = max(e.timestamp for e in events) - min(e.timestamp for e in events)
    rate = total / max(1, duration)
    rh = analysis_rhythm(events)
    hk = analysis_hooks(events)
    pr = analysis_predictions(events)
    hv = analysis_hover_conversion(events)
    return {
        'n': total,
        'duration': duration,
        'rate_per_min': rate * 60,
        'cat_shares': cat_shares,
        'top_routes': top_routes,
        'dominant_period_min': (rh.get('dominant_period_seconds') or 0) / 60 if rh.get('available') else 0,
        'n_bursts': len(rh.get('bursts', [])) if rh.get('available') else 0,
        'hook_lifts': hk.get('category_lifts', {}) if hk.get('available') else {},
        'hover_lift': hv.get('lift', 1.0) if hv.get('available') else 0,
        'route_accuracy': pr.get('route_accuracy', 0) if pr.get('available') else 0,
        'cv_route_mean': pr.get('cv_route_mean', 0) if pr.get('available') else 0,
    }


def render_diff_overview(a: dict, b: dict, label_a: str, label_b: str) -> str:
    """Headline metric comparison: A vs B side by side."""
    W, H = 900, 320
    parts = [svg_tag(W, H)]
    PAD = 40

    headline_pairs = [
        ('events',          f"{a.get('n', 0)}",                    f"{b.get('n', 0)}"),
        ('duration',        humanize_duration(a.get('duration', 0)), humanize_duration(b.get('duration', 0))),
        ('rate (ev/min)',   f"{a.get('rate_per_min', 0):.1f}",      f"{b.get('rate_per_min', 0):.1f}"),
        ('rhythm (min)',    f"{a.get('dominant_period_min', 0):.1f}", f"{b.get('dominant_period_min', 0):.1f}"),
        ('hover lift',      f"{a.get('hover_lift', 0):.2f}×",        f"{b.get('hover_lift', 0):.2f}×"),
        ('CV accuracy',     f"{a.get('cv_route_mean', 0)*100:.1f}%", f"{b.get('cv_route_mean', 0)*100:.1f}%"),
    ]

    col_w = (W - 3 * PAD) / 2
    # Titles
    parts.append(f'<text x="{PAD + col_w/2}" y="30" class="label-sm" text-anchor="middle" fill="#00ffd1">{html_lib.escape(label_a)}</text>')
    parts.append(f'<text x="{PAD + col_w + PAD + col_w/2}" y="30" class="label-sm" text-anchor="middle" fill="#ff4fd8">{html_lib.escape(label_b)}</text>')

    for i, (lbl, va, vb) in enumerate(headline_pairs):
        y = 70 + i * 38
        parts.append(f'<text x="{W/2}" y="{y}" class="label-xs" text-anchor="middle" fill="#5a8ca0">{lbl}</text>')
        parts.append(f'<text x="{PAD + col_w - 10}" y="{y + 4}" class="label-sm" text-anchor="end" fill="#00ffd1">{va}</text>')
        parts.append(f'<text x="{PAD + col_w + PAD + 10}" y="{y + 4}" class="label-sm" text-anchor="start" fill="#ff4fd8">{vb}</text>')

    parts.append('</svg>')
    return ''.join(parts)


def render_diff_category_mix(a: dict, b: dict, label_a: str, label_b: str) -> str:
    """Show category share as paired back-to-back bars (pyramid style)."""
    W = 780
    PAD = 40
    cats = ['view', 'hover', 'react', 'act', 'msg', 'compose', 'search', 'ad']
    row_h = 30
    H = PAD + row_h * len(cats) + 60
    parts = [svg_tag(W, H)]

    mid = W / 2
    bar_max = (W - 2 * PAD) / 2 - 60
    a_shares = a.get('cat_shares', {})
    b_shares = b.get('cat_shares', {})
    max_share = max([a_shares.get(c, 0) for c in cats] + [b_shares.get(c, 0) for c in cats] + [0.01])

    # Headers
    parts.append(f'<text x="{mid - bar_max - 20}" y="{PAD}" class="label-sm" text-anchor="end" fill="#00ffd1">{html_lib.escape(label_a)}</text>')
    parts.append(f'<text x="{mid + bar_max + 20}" y="{PAD}" class="label-sm" text-anchor="start" fill="#ff4fd8">{html_lib.escape(label_b)}</text>')

    for i, cat in enumerate(cats):
        y = PAD + 20 + i * row_h
        color = CATEGORY_COLORS[cat]
        sa = a_shares.get(cat, 0)
        sb = b_shares.get(cat, 0)
        wa = bar_max * sa / max_share
        wb = bar_max * sb / max_share
        # Category label at center
        parts.append(f'<text x="{mid}" y="{y + 5}" class="label-sm" text-anchor="middle" fill="{color}">{cat}</text>')
        # Left bar (A)
        parts.append(f'<rect x="{mid - 40 - wa:.1f}" y="{y - 10}" width="{wa:.1f}" height="20" fill="{color}" opacity="0.8"/>')
        parts.append(f'<text x="{mid - 44 - wa:.1f}" y="{y + 4}" class="label-xs" text-anchor="end" fill="{color}">{sa*100:.1f}%</text>')
        # Right bar (B)
        parts.append(f'<rect x="{mid + 40:.1f}" y="{y - 10}" width="{wb:.1f}" height="20" fill="{color}" opacity="0.8"/>')
        parts.append(f'<text x="{mid + 44 + wb:.1f}" y="{y + 4}" class="label-xs" text-anchor="start" fill="{color}">{sb*100:.1f}%</text>')

    parts.append('</svg>')
    return ''.join(parts)


DIFF_TEMPLATE = HTML_TEMPLATE  # reuse shell; title + sections differ


def build_diff_report(events_a: list[Event], events_b: list[Event],
                      label_a: str = 'A', label_b: str = 'B') -> str:
    """Portrait(A) vs Portrait(B). You on Tuesday vs you on Saturday."""
    sa = _summary_vector(events_a)
    sb = _summary_vector(events_b)

    sections_html = []
    sections_html.append(section(
        '01', 'headline metrics · a vs b',
        f"Side-by-side of the top-level signals between <em>{html_lib.escape(label_a)}</em> and "
        f"<em>{html_lib.escape(label_b)}</em>. Big gaps here mean the two sessions lived in different regimes.",
        render_diff_overview(sa, sb, label_a, label_b), None, anchor='headline',
    ))
    sections_html.append(section(
        '02', 'category mix · what changed',
        "Share of each category in each session. If the A-bar dwarfs the B-bar for <em>hover</em>, "
        "you were more curious; if B's <em>react</em> bar dwarfs A's, you were more committed.",
        render_diff_category_mix(sa, sb, label_a, label_b), None, anchor='mix',
    ))

    # Mini individual reports embedded as side-by-side? Keep simple: just link out.
    # Hook-lift diff
    lift_a = sa.get('hook_lifts', {})
    lift_b = sb.get('hook_lifts', {})
    deltas = []
    for cat in sorted(set(lift_a) | set(lift_b)):
        la = lift_a.get(cat, 1.0); lb = lift_b.get(cat, 1.0)
        deltas.append((cat, la, lb, lb - la))
    deltas.sort(key=lambda t: -abs(t[3]))
    # Simple HTML list (skip SVG for this one)
    hook_rows = ''.join(
        f'<div style="display:flex;padding:6px 0;border-bottom:1px solid rgba(0,255,209,0.1)">'
        f'<span style="flex:1;color:{CATEGORY_COLORS.get(c, "#888")}">{c}</span>'
        f'<span style="flex:0 0 100px;text-align:right;color:#00ffd1">{la:.2f}×</span>'
        f'<span style="flex:0 0 60px;text-align:center;color:#5a8ca0">→</span>'
        f'<span style="flex:0 0 100px;text-align:left;color:#ff4fd8">{lb:.2f}×</span>'
        f'<span style="flex:0 0 80px;text-align:right;color:{("#fff275" if abs(d)>0.3 else "#5a8ca0")}">{d:+.2f}</span>'
        f'</div>'
        for c, la, lb, d in deltas
    )
    sections_html.append(section(
        '03', 'hook drift',
        f"How each category's lift-to-baseline changed from <em>{html_lib.escape(label_a)}</em> to "
        f"<em>{html_lib.escape(label_b)}</em>. Positive delta means the category became a stronger hook.",
        f'<div style="max-width:680px;margin:0 auto;font-size:12px">'
        f'<div style="display:flex;padding:6px 0;color:#5a8ca0;letter-spacing:0.25em;font-size:10px">'
        f'<span style="flex:1">category</span>'
        f'<span style="flex:0 0 100px;text-align:right">{html_lib.escape(label_a)}</span>'
        f'<span style="flex:0 0 60px"></span>'
        f'<span style="flex:0 0 100px;text-align:left">{html_lib.escape(label_b)}</span>'
        f'<span style="flex:0 0 80px;text-align:right">Δ</span>'
        f'</div>{hook_rows}</div>', None, anchor='hook-drift',
    ))

    generated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return DIFF_TEMPLATE.format(
        title=html_lib.escape(f'diff · {label_a} vs {label_b}'),
        generated=generated,
        span='—',
        n_events=sa.get('n', 0) + sb.get('n', 0),
        n_actions=0, n_surfaces=0, n_hovers=0, n_ads=0, n_segments=2,
        duration_human=f"{humanize_duration(sa.get('duration',0))} / {humanize_duration(sb.get('duration',0))}",
        version=VERSION,
        sections='\n'.join(sections_html),
    )


# ═══════════════════════════════════════════════════════════════
# LONGITUDINAL SQLITE STORE  (v0.2.0)
# For multi-week / multi-month captures.
# ═══════════════════════════════════════════════════════════════

STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    seq INTEGER,
    req INTEGER,
    timestamp REAL NOT NULL,
    route TEXT,
    friendly TEXT,
    label TEXT,
    category TEXT,
    rev TEXT,
    ccg TEXT,
    url_path TEXT,
    user_hash TEXT,
    latency_ms REAL DEFAULT 0,
    response_size INTEGER DEFAULT 0,
    segment_id INTEGER,
    kind TEXT DEFAULT 'request'
);
CREATE INDEX IF NOT EXISTS idx_ts   ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_cap  ON events(capture_id);
CREATE INDEX IF NOT EXISTS idx_cat  ON events(category);
CREATE INDEX IF NOT EXISTS idx_user ON events(user_hash);

CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY,
    source_path TEXT,
    ingested_at TEXT,
    n_events INTEGER,
    t_min REAL, t_max REAL
);
"""


def store_path_default() -> Path:
    return Path(__file__).parent / 'reflex_store.sqlite'


def store_connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = db_path or store_path_default()
    con = sqlite3.connect(str(db_path))
    con.executescript(STORE_SCHEMA)
    return con


def store_ingest(path: Path, db_path: Optional[Path] = None, capture_id: Optional[str] = None) -> int:
    """Ingest an NDJSON file into the longitudinal store. Idempotent per capture_id.

    Returns number of events written. User IDs are SHA-256 hashed at rest for
    per-install salting — we need *distinguishability* between accounts, not identity.
    """
    import hashlib
    events = parse_ndjson(path)
    if not events:
        return 0
    capture_id = capture_id or f"{path.name}:{int(events[0].timestamp)}"
    con = store_connect(db_path)
    try:
        # Remove prior ingest with same capture_id
        con.execute('DELETE FROM events WHERE capture_id = ?', (capture_id,))
        con.execute('DELETE FROM captures WHERE capture_id = ?', (capture_id,))

        def user_hash(u: str) -> str:
            if not u:
                return ''
            return hashlib.sha256(f'reflex-salt-{u}'.encode()).hexdigest()[:12]

        rows = [
            (capture_id, e.seq, e.req, e.timestamp, e.route, e.friendly, e.label,
             e.category, e.rev, e.ccg, e.url_path, user_hash(e.user),
             e.latency_ms, e.response_size, e.segment_id, e.kind)
            for e in events
        ]
        con.executemany(
            'INSERT INTO events (capture_id, seq, req, timestamp, route, friendly, label, '
            'category, rev, ccg, url_path, user_hash, latency_ms, response_size, segment_id, kind) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows
        )
        con.execute(
            'INSERT INTO captures (capture_id, source_path, ingested_at, n_events, t_min, t_max) '
            'VALUES (?,?,?,?,?,?)',
            (capture_id, str(path), datetime.now(timezone.utc).isoformat(),
             len(events), events[0].timestamp, events[-1].timestamp)
        )
        con.commit()
    finally:
        con.close()
    return len(events)


def store_list_captures(db_path: Optional[Path] = None) -> list[dict]:
    con = store_connect(db_path)
    rows = con.execute(
        'SELECT capture_id, source_path, ingested_at, n_events, t_min, t_max '
        'FROM captures ORDER BY t_min'
    ).fetchall()
    con.close()
    return [
        {'capture_id': r[0], 'source_path': r[1], 'ingested_at': r[2],
         'n_events': r[3], 't_min': r[4], 't_max': r[5]}
        for r in rows
    ]


def store_events_for_capture(capture_id: str, db_path: Optional[Path] = None) -> list[Event]:
    con = store_connect(db_path)
    rows = con.execute(
        'SELECT req, route, timestamp, ccg, rev, friendly, label, category, seq, url_path, '
        'user_hash, latency_ms, response_size, segment_id, kind '
        'FROM events WHERE capture_id = ? ORDER BY timestamp, req', (capture_id,)
    ).fetchall()
    con.close()
    events = []
    for r in rows:
        icon = '◌'
        events.append(Event(
            req=r[0] or 0, route=r[1] or '', timestamp=r[2], ccg=r[3] or 'GOOD',
            rev=r[4], friendly=r[5] or '', label=r[6] or '', icon=icon,
            category=r[7] or 'nav', seq=r[8] or 0, url_path=r[9] or '',
            user=r[10] or '', latency_ms=r[11] or 0, response_size=r[12] or 0,
            segment_id=r[13] or 0, kind=r[14] or 'request',
        ))
    return events


# ═══════════════════════════════════════════════════════════════
# MAIN — multi-subcommand CLI with legacy compat
# ═══════════════════════════════════════════════════════════════

def cmd_report(args) -> int:
    if not args.input.exists():
        print(f"error: input file {args.input} not found", file=sys.stderr)
        return 1
    print(f"▸ reading {args.input}...", file=sys.stderr)
    events = parse_ndjson(args.input)
    if not events:
        print("error: no valid events found", file=sys.stderr)
        return 1
    n_seg = len(set(e.segment_id for e in events))
    print(f"  parsed {len(events)} events across {n_seg} session segment(s)", file=sys.stderr)
    print("▸ running analyses (this may take a few seconds for permutation tests)...", file=sys.stderr)
    html_out = build_report(events, title=args.title)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_out, encoding='utf-8')
    print(f"▸ wrote {args.output} ({len(html_out):,} bytes)", file=sys.stderr)
    return 0


def cmd_diff(args) -> int:
    if not args.a.exists() or not args.b.exists():
        print(f"error: both inputs must exist", file=sys.stderr)
        return 1
    print(f"▸ reading {args.a}...", file=sys.stderr)
    ea = parse_ndjson(args.a)
    print(f"▸ reading {args.b}...", file=sys.stderr)
    eb = parse_ndjson(args.b)
    if not ea or not eb:
        print("error: empty input(s)", file=sys.stderr)
        return 1
    la = args.label_a or args.a.stem
    lb = args.label_b or args.b.stem
    print(f"▸ building diff portrait ({la} vs {lb})...", file=sys.stderr)
    html_out = build_diff_report(ea, eb, la, lb)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_out, encoding='utf-8')
    print(f"▸ wrote {args.output} ({len(html_out):,} bytes)", file=sys.stderr)
    return 0


def cmd_discover(args) -> int:
    """Inline pattern-discovery — scans unmatched friendly_names and prints suggestions."""
    if not args.input.exists():
        print(f"error: input file {args.input} not found", file=sys.stderr)
        return 1
    events = parse_ndjson(args.input)
    if not events:
        return 1
    unmatched: Counter = Counter()
    for e in events:
        if e.friendly and e.label in ('Performing action', 'Loading data', 'Unknown activity'):
            unmatched[e.friendly] += 1
    if not unmatched:
        print("✓ 100% decoder coverage — nothing to discover.", file=sys.stderr)
        return 0
    print(f"\n▸ {len(unmatched)} unique unmatched friendly_names "
          f"(across {sum(unmatched.values())} events):\n", file=sys.stderr)
    for name, count in unmatched.most_common(50):
        suf = '[MUT]' if name.endswith('Mutation') else ('[QRY]' if name.endswith('Query') else '[?  ]')
        print(f"  {count:5d}  {suf}  {name}", file=sys.stderr)
    print(f"\n  For more advanced clustering + pattern suggestions, run:", file=sys.stderr)
    print(f"    python reflex_discover.py {args.input}", file=sys.stderr)
    return 0


def cmd_store_ingest(args) -> int:
    if not args.input.exists():
        print(f"error: input file {args.input} not found", file=sys.stderr)
        return 1
    db = args.db or store_path_default()
    print(f"▸ ingesting {args.input} into {db}...", file=sys.stderr)
    n = store_ingest(args.input, db_path=db, capture_id=args.capture_id)
    print(f"▸ wrote {n} events", file=sys.stderr)
    return 0


def cmd_store_list(args) -> int:
    db = args.db or store_path_default()
    caps = store_list_captures(db_path=db)
    if not caps:
        print(f"no captures in {db}", file=sys.stderr)
        return 0
    print(f"\n{len(caps)} capture(s) in {db}:\n")
    for c in caps:
        t0 = datetime.fromtimestamp(c['t_min'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        t1 = datetime.fromtimestamp(c['t_max'], tz=timezone.utc).strftime('%H:%M')
        dur = humanize_duration(c['t_max'] - c['t_min'])
        print(f"  {c['capture_id']:<50}  {c['n_events']:>6} events  {t0} → {t1}  ({dur})")
    return 0


def cmd_store_report(args) -> int:
    db = args.db or store_path_default()
    events = store_events_for_capture(args.capture_id, db_path=db)
    if not events:
        print(f"no events for capture_id {args.capture_id}", file=sys.stderr)
        return 1
    html_out = build_report(events, title=args.title or args.capture_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_out, encoding='utf-8')
    print(f"▸ wrote {args.output} ({len(html_out):,} bytes)", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog='reflex',
        description='Reflex v%s — mirror analysis for Session Cosmos captures.' % VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Subcommands:
  report    — single-session portrait (default if first arg is an .ndjson)
  discover  — list unmatched friendly_names for decoder expansion
  diff      — portrait(A) vs portrait(B). "You on Tuesday vs Saturday."
  store     — longitudinal SQLite store (ingest / list / report)

Examples:
  python reflex.py report capture.ndjson -o report.html
  python reflex.py discover capture.ndjson
  python reflex.py diff monday.ndjson saturday.ndjson -o diff.html
  python reflex.py store ingest capture.ndjson
  python reflex.py store list
  python reflex.py store report <capture_id> -o longitudinal.html

Legacy form still works:
  python reflex.py capture.ndjson -o report.html
""")
    sub = p.add_subparsers(dest='cmd')

    pr = sub.add_parser('report', help='Build a portrait from one NDJSON.')
    pr.add_argument('input', type=Path)
    pr.add_argument('-o', '--output', type=Path, default=Path('report.html'))
    pr.add_argument('--title', type=str, default='session')
    pr.set_defaults(func=cmd_report)

    pd = sub.add_parser('diff', help='Cross-session diff portrait.')
    pd.add_argument('a', type=Path)
    pd.add_argument('b', type=Path)
    pd.add_argument('-o', '--output', type=Path, default=Path('diff.html'))
    pd.add_argument('--label-a', dest='label_a', type=str, default=None)
    pd.add_argument('--label-b', dest='label_b', type=str, default=None)
    pd.set_defaults(func=cmd_diff)

    pdisc = sub.add_parser('discover', help='List unmatched friendly_names.')
    pdisc.add_argument('input', type=Path)
    pdisc.set_defaults(func=cmd_discover)

    pst = sub.add_parser('store', help='Longitudinal SQLite operations.')
    pst_sub = pst.add_subparsers(dest='store_cmd')

    psti = pst_sub.add_parser('ingest', help='Ingest an NDJSON into the store.')
    psti.add_argument('input', type=Path)
    psti.add_argument('--db', type=Path, default=None)
    psti.add_argument('--capture-id', dest='capture_id', type=str, default=None)
    psti.set_defaults(func=cmd_store_ingest)

    pstl = pst_sub.add_parser('list', help='List captures in the store.')
    pstl.add_argument('--db', type=Path, default=None)
    pstl.set_defaults(func=cmd_store_list)

    pstr = pst_sub.add_parser('report', help='Build a portrait from a stored capture.')
    pstr.add_argument('capture_id', type=str)
    pstr.add_argument('-o', '--output', type=Path, default=Path('report.html'))
    pstr.add_argument('--title', type=str, default=None)
    pstr.add_argument('--db', type=Path, default=None)
    pstr.set_defaults(func=cmd_store_report)

    # Legacy compatibility: if first non-flag arg ends with .ndjson, treat as 'report'
    argv = sys.argv[1:]
    if argv and not argv[0].startswith('-') and argv[0] not in ('report', 'diff', 'discover', 'store'):
        if argv[0].endswith('.ndjson') or Path(argv[0]).exists():
            argv = ['report'] + argv

    args = p.parse_args(argv)
    if not hasattr(args, 'func'):
        p.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print('\n▸ interrupted.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
