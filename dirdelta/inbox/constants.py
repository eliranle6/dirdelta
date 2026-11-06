"""The inbox sort's keys, timings, labels and colors"""
from dirdelta.ui import opening
from dirdelta.ui import picker


# The label of the inbox's screens, so they're told from a sync's
LABEL = ('SORT', 'cyan')
# How wide the preview column's wrapped lines are, at most
PREVIEW_WIDTH = 40
# How often the picker's previews are looked at for changes (Claude's descriptions coming in), and
# how often Ask where they go looks whether the descriptions it waits for came, in seconds
PREVIEWS_INTERVAL = 0.3
DESCRIBED_WAIT_INTERVAL = 0.2
# The key that describes the picked files (or the selected one) with Claude, in the background
DESCRIBE_KEY = '\t'
# Seconds between Claude's downloads with the Drive lock free, for whoever waits for it (see _ai_files())
LOCK_GAP = 0.001
# The key that opens the selected file (Ctrl-X) with its program (see opening.py)
OPEN_KEY = opening.KEY
# How many of a dir's file names Claude is given, so it sees how they're named
NAMES_PER_DIR = 3
# What says a file of the inbox is in the sorted tree already, in its preview: highlighted
SURELY_A_COPY = picker.highlighted("\u2192 a copy: it may be removed")
# What says a file looks like junk, in its preview: in yellow, since it's a guess, not a copy's sure
# green
MAYBE_JUNK = picker.highlighted("\u2192 junk? it may be removed", 'yellow')
# What a file that looks like junk is shown as, after its name (and its description): a search
# (/) for 'junk?' finds them all
JUNK_BY_NAME = "[junk? %s]"
JUNK_BY_CLAUDE = "[claude: junk? %s]"
# What a file being described is shown as, after its name
LOOKING = "(Claude is looking at it...)"
# What a file Claude described is shown as, after its name: a search (/) for 'claude:' finds them,
# and one for a word finds the files Claude said it of
DESCRIBED = "[claude: %s]"
# The style of what Claude says, after a file's name (see picker.styled()): in Claude's color, as
# its options' in the action menu (VERB_COLORS)
CLAUDE_STYLE = 'magenta'
# The titles of what Claude says, in the preview column
DESCRIPTION_TITLE = "Description (ai):"
DESTINATION_TITLE = "Dest. path recommendation (ai):"
# The title of whether the sorted tree has the file already (by its contents)
IN_SORTED_TREE_TITLE = "Is in replica dir:"
DIR_TITLE = "Dir recommendation (ai):"
LOOKING_AT_DIR = "(Claude is looking at the dir...)"
# How many of a dir's files Claude describes (reading them) when it's asked about the dir as a whole,
# and the most of them whose dates are read for it
DIR_FILES_DESCRIBED = 4
DIR_FILES_DATED = 200


# What an option of the action menu does to the files, and its color: its text's, and its label's
# in the lines below the menu (Claude's in magenta, as what comes from Claude there)
ASK = 'claude'
MOVE = 'move'
COPY = 'copy'
REMOVE = 'remove'
OPEN = 'open'
READ = 'read'
VERB_COLORS = {ASK: 'magenta', MOVE: 'blue', COPY: 'cyan', REMOVE: 'red', OPEN: 'green', READ: 'yellow'}
# A part of a destination's path: where it comes from, and its bracket's color and names (the
# first that fits), e.g. [Claude's dir] (Claude's in magenta, as its options' color)
SORTED_TREE = ((None), ("sorted tree", "tree"))
THE_INBOX = (None, ("the inbox", "inbox"))
CLAUDES_DIR = ('magenta', ("Claude's dir", "Claude's", "Claude"))
CLAUDES_NAME = ('magenta', ("Claude's name", "Claude's", "Claude"))
YOUR_DIR = ('yellow', ("your pick", "yours"))
YOUR_NAME = ('yellow', ("you type it", "yours"))
OWN_NAME = ('green', ("its own name", "own name", "own"))
