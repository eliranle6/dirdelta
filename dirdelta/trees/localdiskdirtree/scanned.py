"""A local replica with a tree of its files too (LocalDiskDirTree), scanned"""
from dirdelta.trees import localscan
from dirdelta.trees.localdiskdirtree.replica import LocalReplica
from dirdelta.ui import messages


def factory(filesystem_dirpath, max_depth=None, silent=False):
    dirtree = LocalDiskDirTree(filesystem_dirpath, silent, max_depth)
    dirtree.update_from_filesystem()
    return dirtree


class LocalDiskDirTree(LocalReplica):
    """A LocalReplica with a tree of its files too (which is empty until update_from_filesystem(), which
    scans down to max_depth levels below it), as a diff with a Drive replica's tree needs"""
    def update_from_filesystem(self):
        """Add the dirs and files on disk (hidden ones too), down to max_depth levels below the root."""
        if not self._silent:
            messages.print_line("Scanning directory %s..." % (self._rootpath,))
        scan = localscan.scan(self._rootpath, self.max_depth)
        self.scan_errors = scan.errors
        for relpath, (kind, _, _) in scan.entries.items():
            if kind == localscan.FILE:
                self.add_file_by_relpath(relpath)
            else:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
        self.file_stamps = scan.files()

    def rescan(self):
        """See what's on disk now: the tree is replaced only once the new scan is done, so it's as it
        was if it's stopped. Raises OSError if the dir isn't there anymore (e.g. it was unmounted), and
        then too."""
        super(LocalDiskDirTree, self).rescan()
        scanned = LocalDiskDirTree(self._rootpath, True, self.max_depth)
        scanned.update_from_filesystem()
        is_trashing, silent, listeners = self._is_trashing, self._silent, self._listeners
        self.__dict__.update(scanned.__dict__)
        self._is_trashing, self._silent, self._listeners = is_trashing, silent, listeners

    def _file_added(self, relpath):
        self.add_file_by_relpath(relpath)
        super(LocalDiskDirTree, self)._file_added(relpath)

    def _file_removed(self, relpath):
        if relpath in self:
            self.remove_node(relpath)
        super(LocalDiskDirTree, self)._file_removed(relpath)

    def _file_moved(self, relpath, new_relpath):
        if relpath in self:
            self.remove_node(relpath)
            self.add_file_by_relpath(new_relpath)
        super(LocalDiskDirTree, self)._file_moved(relpath, new_relpath)

    def _dir_removed(self, relpath):
        if relpath in self:
            self.remove_node(relpath)

    def _dir_moved(self, dirpath, new_dirpath, to):
        super(LocalDiskDirTree, self)._dir_moved(dirpath, new_dirpath, to)
        if isinstance(to, LocalDiskDirTree):
            self._move_subtree(dirpath, new_dirpath, to)
        elif dirpath in self:
            self.remove_node(dirpath)
