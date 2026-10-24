"""Whether dirdelta changes files. Unless DRYRUN=0 is set it's a dry run: actions that change files
(copying, removing) only say what they would do."""
import os

# Read at each use (rather than imported by value), so tests can patch it
DRYRUN = os.environ.get("DRYRUN") != "0"


def label():
    """The mode's label for the screens, and its color: green for a dry run, red for a live one."""
    return ("DRY RUN", "green") if DRYRUN else ("LIVE", "red")
