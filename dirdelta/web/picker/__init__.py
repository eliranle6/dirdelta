"""treepicker in the browser: a picker's command (its arguments, its items on stdin, and the pipes
dirdelta makes for it) done by the web page instead of the terminal program, so every picker, and every
flow that uses them, is the same in the browser (see docs/treepicker-integration.md for the protocol)."""
from dirdelta.web.picker.screen import PickerScreen  # noqa: F401
from dirdelta.web.picker.spec import SpecError, parse  # noqa: F401
