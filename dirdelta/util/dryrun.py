"""Whether dirdelta changes files. Unless DRYRUN=0 is set it's a dry run: actions that change files
(copying, removing) only say what they would do."""
import os

# Read at each use (rather than imported by value), so tests can patch it
DRYRUN = os.environ.get("DRYRUN") != "0"

# What a confirmation says in a dry run, after what it asks: in the terminal, and in the web version (whose top
# bar switches it)
NOTE = "(A dry run: nothing on disk will change. DRYRUN=0 changes files.)"
WEB_NOTE = "(A dry run: nothing will change. Switch to LIVE in the top bar to change files.)"


def note():
    """What a confirmation says in a dry run, where it's shown"""
    from dirdelta.ui import frontend
    return NOTE if frontend.current is None else WEB_NOTE


def label():
    """The mode's label for the screens, and its color: green for a dry run, red for a live one."""
    return ("DRY RUN", "green") if DRYRUN else ("LIVE", "red")


def set_live(live):
    """Change files from now on (live), or only say what would be done: the web version's DRY RUN label
    switches it, while nothing's running (until the daemon restarts, which starts as DRYRUN says)"""
    global DRYRUN
    DRYRUN = not live
