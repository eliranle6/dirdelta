"""dirdelta's C++ programs (treepicker, dirdiff), from the lib/treepicker submodule: finding them."""
import os
import shutil
import sys

# Where make build put them, when running from the source tree (bin/python and make set it)
PROGRAMS_DIR_VARIABLE = 'DIRDELTA_PROGRAMS_DIR'


class ProgramError(Exception):
    """A program that can't be found, or failed"""


def find(name):
    """The program: in this copy's build, when running from source (make build; bin/python says
    where); else next to the Python running dirdelta, where make install and make deploy put it;
    else on PATH."""
    # Not resolving sys.executable's links: a venv's python links to the system's
    for directory in (os.environ.get(PROGRAMS_DIR_VARIABLE), os.path.dirname(sys.executable)):
        candidate = os.path.join(directory, name) if directory else None
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    program = shutil.which(name)
    if not program:
        raise ProgramError(
            '%s was not found. Build it with make build (and run dirdelta with bin/python), or install it '
            'with make install or make deploy.' % name)
    return program
