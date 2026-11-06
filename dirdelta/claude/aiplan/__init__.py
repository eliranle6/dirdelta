"""Asking AI about files: the user says what they want in their own words, and the AI answers it (if
it's a question), or with a plan, steps of the actions a screen offers it (copy, move, remove...), for
the user to review. Nothing here does anything to a file, or shows anything: see aiplan_screen.py, and
the sync and the inbox's sort, which do what's approved.

It's told the files' paths and sizes, and what's known of them (a Task). Of the files the user is on
(its focus), at most MAX_FOCUS, it's told what's in a zip, and may read the others, which sends their
contents to it; of the rest, it gets no contents. All it says is checked here, as it could be anything:
only the files it was told of, one step each, and only targets that can be.

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.claude.aiplan.asking import make, too_many  # noqa: F401
from dirdelta.claude.aiplan.prompt import focus_of  # noqa: F401
from dirdelta.claude.aiplan.kinds import (MAX_FILES, MAX_FOCUS, MAX_MEMBERS, MAX_OTHERS, Action, File,  # noqa: F401
                                          Plan, Step, Task)
