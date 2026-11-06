"""The hashing screens' key, and the dashboard's options (what each is, by replica) and headings"""
from dirdelta.hashes import hashing
from dirdelta.trees import localdiskdirtree
from dirdelta.util import text


# The file pickers' key that shows the dashboard
KEY = '#'
# What the file pickers' keys row says of it
KEY_HINT = (KEY, "replicas dashboard")
# What ? says in the file pickers of the tags hashing adds after the files' names
HELP_LINES = ["Tags after a file's name (/ searches them too):",
              "  %-24s its contents' hash is known (any name, any size: it's found by it)" % (hashing.HASHED_TAG,),
              "  %-24s being read now" % (hashing.HASHING_TAG,),
              "  %-24s matched by its name and size only, for now" % (hashing.NOT_HASHED_TAG,),
              "  %-24s unreadable, or it changed while it was read" % (hashing.FAILED_TAG,)]


NOTHING = "Nothing: go back"
NOT_NOW = "Not now (%s starts it later)" % (KEY,)
HASH_AND_WAIT = "Hash now, and wait"
HASH_IN_BACKGROUND = "Hash in the background, and go on"
KEEP_HASHING = "Don't quit: keep hashing"
QUIT_ANYWAY = "Quit"
# How often the wait's progress line changes, in seconds
WAIT_INTERVAL = 0.5


def _files(count):
    return text.files(count, grouped=True)


is_local = localdiskdirtree.is_local


# The dashboard's options: each (one of these, the replica's path), its text what shown_as says
_HEADING_TEXT = "\u2500\u2500 %s \u2500\u2500"
_HASH = 'hash'
_HEADING, _INFO, _KNOWN, _BAR, _STATE, _TOGGLE, _FILES, _RESCAN, _DRIVE, _DRIVE_NOTE, _LABEL = (
    'heading', 'info', 'known', 'bar', 'state', 'toggle', 'files', 'rescan', 'drive', 'drive note', 'label')
BACK = "Back"
TITLE = "Replicas dashboard"


REPLICAS_HEADING = '\u2550\u2550 Replicas \u2550\u2550'
PAIRS_HEADING = '\u2550\u2550 Pairs: what\'s synced to what \u2550\u2550'
_PAIR, _PAIR_STATE = 'pair', 'pair state'


INBOXES_HEADING = '\u2550\u2550 Inboxes (files waiting to be sorted) \u2550\u2550'
