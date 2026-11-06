"""dirdelta's pickers: they run the treepicker program, from github.com/eliranle6/treepicker.

Like fzf, treepicker draws on the terminal itself and prints what was picked, so each pick runs it as
a subprocess (see docs/treepicker-integration.md), found by programs.find() (where make install,
make deploy or make build put it, or else on PATH).

Its parts are in the modules here; the names the rest of dirdelta uses are here too, so
picker.pick_option() (say) is the same function as picker.menus.pick_option(), and patching it
here patches what dirdelta calls.
"""
from dirdelta.ui.picker.files import key_help_lines, pick_files, view_files  # noqa: F401
from dirdelta.ui.picker.kinds import BLANK, Colored, Disabled, Option, Picked, Side, SIDE_KEY, Skipped  # noqa: F401
from dirdelta.ui.picker.menus import option_id, option_label, pick_option  # noqa: F401
from dirdelta.ui.picker.places import place, trail  # noqa: F401
from dirdelta.ui.picker.command import PickerError  # noqa: F401
from dirdelta.ui.picker.selection import PickerClosed, Selection  # noqa: F401
from dirdelta.ui.picker.styles import (HIGHLIGHT_MARK, display_width, grouped, highlighted,  # noqa: F401
                                       segments, shortcut_prefixes, styled, unstyled)
from dirdelta.ui.picker.trees import pick_from_tree, pick_under_dir  # noqa: F401
from dirdelta.ui.picker.updates import log_error, set_ambient_status  # noqa: F401
