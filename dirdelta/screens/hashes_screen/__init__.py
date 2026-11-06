"""The screens of hashing local replicas' files (hashing.py): whether to hash a replica's files
when it's opened (offer()), and waiting for it (wait()); the dashboard (dashboard()): each replica's
progress, pausing and resuming it, and its files, hashed or not; and what the file pickers show of it
(Marks): a label for each replica on the bottom line, in a color by how far it got (red, orange,
yellow, then green once it's all hashed), and a mark before each file's name.

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.screens.hashes_screen.dashboard_screen import dashboard  # noqa: F401
from dirdelta.screens.hashes_screen.files import view_files  # noqa: F401
from dirdelta.screens.hashes_screen.marks import Marks, picker_status  # noqa: F401
from dirdelta.screens.hashes_screen.names import (BACK, HELP_LINES, KEY, KEY_HINT, PAIRS_HEADING,  # noqa: F401
                                                  REPLICAS_HEADING, TITLE)
from dirdelta.screens.hashes_screen.names import (HASH_AND_WAIT, HASH_IN_BACKGROUND, KEEP_HASHING, NOT_NOW,  # noqa: F401
                                                  NOTHING, QUIT_ANYWAY)
from dirdelta.screens.hashes_screen.offering import hashing_status, jobs_of, offer, prepare, scan_with_listing  # noqa: F401
from dirdelta.screens.hashes_screen.waiting import is_ok_to_quit, wait  # noqa: F401
