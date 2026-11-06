"""A tree of a dir's files and dirs (DirTree), the base of the replicas' trees: a local dir's
(localdiskdirtree.py) and a Drive folder's (clouddirtree).

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.trees.dirtree.common import HashStopped  # noqa: F401
from dirdelta.trees.dirtree.tree import DirTree  # noqa: F401
