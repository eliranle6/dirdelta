"""Opening a picker's files with their programs (xdg-open), as if double-clicked: Ctrl-X in the
inbox's and a sync's file pickers (on the picked files, or else the selected one), or Open in their
action menus. A Drive file is downloaded first, into downloads.DOWNLOADS_DIR (or found downloaded
there). It's done in the background, one file after another, while the picker is shown: its status
bar says how far the downloads got, in all (Opener.status_parts()), and each file being downloaded
says how far it got, in a tag after its name (Opener.tags()), as hashing's do.

More than one file to download is asked about first: Ctrl-X asks on the status bar, and pressed
again soon (in CONFIRM_FOR seconds) on the same files, goes ahead (so the picker stays); the menu's

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.ui.opening.names import (COLOR, CONFIRM_NO, CONFIRM_YES, DOWNLOADING_TAG, KEY, KEY_HINT,  # noqa: F401
                                       OPENED_TAG, WAITING_TAG, tag_style)
from dirdelta.ui.opening.opener import Opener  # noqa: F401
from dirdelta.ui.opening.screens import confirm, with_tags  # noqa: F401
