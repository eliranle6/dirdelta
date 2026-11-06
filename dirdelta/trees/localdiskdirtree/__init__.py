"""A local dir as a replica: LocalReplica, whose files are asked of the disk as they are now, and
LocalDiskDirTree, which keeps a tree of them too (as a diff with a Drive replica needs).

Its parts are in the modules here; the names the rest of dirdelta uses are here too (but _trash():
patch it in fs)."""
from dirdelta.trees.localdiskdirtree.fs import PART_PREFIX  # noqa: F401
from dirdelta.trees.localdiskdirtree.replica import MAX_SCAN_ERRORS_SHOWN, LocalReplica, is_local, scan_warning  # noqa: F401
from dirdelta.trees.localdiskdirtree.scanned import LocalDiskDirTree, factory  # noqa: F401
