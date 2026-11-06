"""A local dir as a replica (LocalReplica), its files asked of the disk; what it does with them
are mixins, each in a module here"""
import contextlib
import os

from dirdelta.trees import dirtree
from dirdelta.trees.localdiskdirtree.copying import LocalCopying
from dirdelta.trees.localdiskdirtree.local_info import LocalInfo
from dirdelta.trees.localdiskdirtree.moving import LocalMoving
from dirdelta.trees.localdiskdirtree.removing import LocalRemoving
from dirdelta.util import text


# How many of a listing's error messages a scan warning lists
MAX_SCAN_ERRORS_SHOWN = 3


def is_local(tree):
    """Whether the tree is a local replica's (else, e.g., a Drive one's)"""
    return isinstance(tree, LocalReplica)


def scan_warning(where, errors, so="the diff may be wrong"):
    """A warning's lines if scanning where (a dir, or a description of dirs) couldn't read everything,
    given find's error messages, since then (so) a diff may list files as missing that are there, or
    miss some; no lines if there are no errors."""
    if not errors:
        return []
    lines = ["Couldn't read everything in %s (%s), so %s:" %
             (where, text.counted(len(errors), 'error'), so)]
    return lines + text.listed(["  " + error for error in errors], MAX_SCAN_ERRORS_SHOWN)


class LocalReplica(LocalInfo, LocalCopying, LocalRemoving, LocalMoving, dirtree.DirTree):

    """A local dir, whose files are asked of the disk, not of a tree of them (it has none: dirdiff
    diffs two local dirs, and an inbox's are listed): what it says is as things are now. What keeps a
    tree too is LocalDiskDirTree, told of each change by _file_added() and the like; what listens
    (see DirTree.add_listener()) is told by them."""
    def __init__(self, filesystem_dirpath, silent=True, max_depth=None):
        """Down to max_depth levels below it"""
        filesystem_dirpath = os.path.realpath(filesystem_dirpath)
        super(LocalReplica, self).__init__(rootpath=filesystem_dirpath, silent=silent)
        self.max_depth = max_depth
        # What a listing couldn't read in the last scan (see LocalDiskDirTree), so a tree may lack
        self.scan_errors = []
        # {relpath: (size, mtime_ns)} of its files, as of the last scan (None: not scanned), so
        # its hashing job needn't list them again (hashing.Job.scan())
        self.file_stamps = None
        # Whether removing a file moves it to the desktop's trash (see trashing())
        self._is_trashing = False

    def _file_added(self, relpath):
        """A file was just made at relpath"""
        self._tell_added(relpath)

    def _file_removed(self, relpath):
        """The file at relpath was just removed"""
        self._tell_removed(relpath)

    def _file_moved(self, relpath, new_relpath):
        """The file at relpath was just moved to new_relpath, in this tree"""
        self._tell_moved(relpath, new_relpath, self)

    def _dir_removed(self, relpath):
        """The (empty) dir at relpath was just removed"""

    def _dir_moved(self, dirpath, new_dirpath, to):
        """The dir at dirpath was just moved, with all in it, to new_dirpath in to (maybe this one)"""
        if self._listeners or to._listeners:
            for new_relpath in to.files_under(new_dirpath):
                if to.has_file(new_relpath):
                    self._tell_moved(dirpath + new_relpath[len(new_dirpath):], new_relpath, to)

    @contextlib.contextmanager
    def trashing(self):
        """Inside, removing a file moves it to the desktop's trash (gio trash), where it can be
        restored from, rather than removing it for good"""
        self._is_trashing = True
        self.REMOVED_TO = " (to the trash)"
        try:
            yield
        finally:
            self._is_trashing = False
            del self.REMOVED_TO

    def rescan(self):
        """See what's on disk now: it's asked anyway, so only whether it's there. Raises OSError if the
        dir isn't there anymore (e.g. it was unmounted)."""
        if not os.path.isdir(self._rootpath):
            raise OSError("%s isn't there anymore" % (self._rootpath,))
        self.scan_errors = []
