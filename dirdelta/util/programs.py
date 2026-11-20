"""dirdelta's C++ programs (treepicker, dirdiff), from the lib/treepicker submodule: finding them."""
import os
import shutil
import subprocess
import sys

# Where make build put them, when running from the source tree (bin/python and make set it)
PROGRAMS_DIR_VARIABLE = 'DIRDELTA_PROGRAMS_DIR'
# The copy of the repo this package is in, when it's run from source (an installed one has no bin/)
SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ProgramError(Exception):
    """A program that can't be found, or failed"""


def source_build_dir():
    """Where make build put the programs of the copy of the repo this package is in (bin/builddir
    says), or None when it isn't run from one: so a run from source finds its own even when it wasn't
    started by bin/python (rather than another program of the same name on PATH, as Debian's dirdiff)."""
    builddir = os.path.join(SOURCE_ROOT, 'bin', 'builddir')
    if not os.access(builddir, os.X_OK):
        return None
    try:
        out = subprocess.run([builddir], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return os.path.join(os.fsdecode(out.stdout.strip()), 'treepicker')


def find(name):
    """The program: in this copy's build, when running from source (make build; bin/python says
    where, else bin/builddir); else next to the Python running dirdelta, where make install and make
    deploy put it; else on PATH."""
    # Not resolving sys.executable's links: a venv's python links to the system's
    for directory in (os.environ.get(PROGRAMS_DIR_VARIABLE), source_build_dir(),
                      os.path.dirname(sys.executable)):
        candidate = os.path.join(directory, name) if directory else None
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    program = shutil.which(name)
    if not program:
        raise ProgramError(
            '%s was not found. Build it with make build (and run dirdelta with bin/python), or install it '
            'with make install or make deploy.' % name)
    return program
