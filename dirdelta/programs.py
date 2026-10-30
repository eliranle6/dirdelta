"""dirdelta's C++ programs (treepicker, dirdiff), from the lib/treepicker submodule: finding them."""
import os
import shutil
import sys

# Where make build puts them, when running from the source tree
SOURCE_TREE_BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'lib', 'treepicker', 'build')


class ProgramError(Exception):
    """A program that can't be found, or failed"""


def find(name):
    """The program: next to the Python running dirdelta, where make install and make deploy put it;
    else the source tree's build (make build), for running from source; else on PATH."""
    # Not resolving sys.executable's links: a venv's python links to the system's
    for candidate in (os.path.join(os.path.dirname(sys.executable), name),
                      os.path.join(SOURCE_TREE_BUILD, name)):
        if os.access(candidate, os.X_OK):
            return candidate
    program = shutil.which(name)
    if not program:
        raise ProgramError(
            '%s was not found. Build it with make build, or install it with make install or make '
            'deploy.' % name)
    return program
