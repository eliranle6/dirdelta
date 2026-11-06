"""The data of DirTree's nodes: a DirEntry for a dir, a FileEntry for a file."""
import os


class _Entry(object):
    """A DirTree node's data.

    Example: the dirtree's root is /home/users/blah and an entry is /home/users/blah/subdir1/subdir2.
    Then name is subdir2, relpath is subdir1/subdir2 and fullpath is /home/users/blah/subdir1/subdir2.
    The root's relpath is ''. relpath is also the entry's node's id in the tree.
    """

    def __init__(self, name, relpath, fullpath):
        self.name = name
        self.relpath = relpath
        self.fullpath = fullpath

    def full_filesystem_path(self):
        return self.fullpath

    def _child_paths(self, name):
        return os.path.join(self.relpath, name), os.path.join(self.fullpath, name)


class DirEntry(_Entry):
    """A DirTree node that represents a filesystem directory."""

    def __repr__(self):
        return self.fullpath


class FileEntry(_Entry):
    def __repr__(self):
        return self.relpath
