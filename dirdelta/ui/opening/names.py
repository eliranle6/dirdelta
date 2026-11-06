"""Opening's key, timings, colors and tags"""
import os

from dirdelta.util import downloads
from dirdelta.util import text


# The file pickers' key that opens the picked files, or the selected one (Ctrl-X), and its keys
# row's hint
KEY = '\x18'
KEY_HINT = ('Ctrl-X', 'open')
# How long the status bar says what was opened, in seconds; and how long Ctrl-X's question waits
# for it again
SHOWN_FOR = 5
CONFIRM_FOR = 10
# How many files are opened at once at most (each in a window of its own)
MAX_OPENED = 10
# The status bar's colors: of a note (what was opened, or why not) and the question, and of the
# downloads' progress (orange, as hashing's)
COLOR = 'yellow'
PROGRESS_COLOR = 'orange'
# The tags after a downloaded file's name: waiting for its turn, how far it got, opened, failed
WAITING_TAG = "[↓ waiting]"
DOWNLOADING_TAG = "[↓ %d%%]"
OPENED_TAG = "[↓ opened]"
FAILED_TAG = "[↓ failed]"


def tag_style(tag):
    """A tag's style (see picker.styled()): downloading in orange, as its status, opened in its note's
    color"""
    return {WAITING_TAG: 'grey', OPENED_TAG: COLOR, FAILED_TAG: 'red'}.get(tag, PROGRESS_COLOR)
# What the confirmation's options are
CONFIRM_NO = 'No'
CONFIRM_YES = 'Yes, download and open them'

WAITING, DOWNLOADING, OPENED, FAILED = 'waiting', 'downloading', 'opened', 'failed'


files_text = text.files


def short_dir():
    """DOWNLOADS_DIR, with ~ for the home dir"""
    home = os.path.expanduser('~')
    path = downloads.DOWNLOADS_DIR
    return '~' + path[len(home):] if path == home or path.startswith(home + os.sep) else path
