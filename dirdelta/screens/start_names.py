"""The start menu's options, sections and what it returns"""
import collections


NOT_CHOSEN = '<none: press Enter to choose one>'
LOCAL = 'Local disk'
CLOUD = 'Google Drive'
QUIT = 'Quit'
KNOWN_LIST = '  Replicas dashboard: every known replica (last updates, files, hashes)'
SORT = '  New sort: choose an inbox, and the sorted tree its files go to (with Claude\'s help)'
# The menu's sections' headings (shown in grey, and skipped when moving: they can't be picked)
SYNC_SECTION = '\u2500\u2500 Sync two replicas \u2500\u2500'
RECENT_SYNCS_SECTION = '\u2500\u2500 Recent syncs \u2500\u2500'
SORT_SECTION = '\u2500\u2500 Sort an inbox into a sorted tree \u2500\u2500'
RECENT_SORTS_SECTION = '\u2500\u2500 Recent inbox sorts \u2500\u2500'
REPLICAS_SECTION = '\u2500\u2500 Replicas \u2500\u2500'
# What a replica the user knows is offered as, when choosing a sorted tree
KNOWN = 'Known replica: '

# What run() returns for an inbox to sort (rather than a pair to sync)
Sort = collections.namedtuple('Sort', ['inbox', 'root'])

# Where a local replica is browsed from, and a cloud one (all of Drive)
LOCAL_ROOT = '/'
CLOUD_ROOT = 'cloud'
