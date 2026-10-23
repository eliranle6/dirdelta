import os
import treelib


def factory_from_list_of_file_entries(files, filesystem_dirpath):
    """A DirTree rooted at filesystem_dirpath holding the given files, at the same relative paths."""
    dirtree = DirTree(os.path.realpath(filesystem_dirpath))
    for file_entry in files:
        dirtree.add_file_by_relpath(file_entry.relpath)
    return dirtree


class _Entry(object):
    """A DirTree node's data.

    Example: the dirtree's root is /home/users/blah and an entry is /home/users/blah/subdir1/subdir2.
    Then name is subdir2, relpath is /subdir1/subdir2 and fullpath is /home/users/blah/subdir1/subdir2.
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


class DirTree(treelib.Tree):
    """
    The tree will be created as follows:
        Root node:
            id='/'
            tag=root path (for instance /home/blah/myfiles/)
            data=Root node entry

    The full filesystem path can be obtained from the data (node.data.full_filesystem_path())
    """
    def __init__(self, rootpath, silent=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._silent = silent

        rootpath = rootpath.rstrip('/') or '/'
        self._rootpath = rootpath
        root = DirEntry(name='/', relpath='/', fullpath=self._rootpath)
        self._create_node_orig = self.create_node
        self._root = self.create_node(identifier='/', tag=root.name, data=root)
        self.create_node = self._create_node_override_method

    def create_dir_node_from_fullpath_if_not_exists(self, fullpath):
        # Convert to relative path
        relpath = os.path.relpath(fullpath, self.fullpath())

        return self.create_dir_node_from_relpath_if_not_exists(relpath)

    def create_dir_node_from_relpath_if_not_exists(self, relpath):
        # Make sure all subdires have nodes
        parts = relpath.split(os.path.sep)
        cur_subdir = self._root
        for subdir_name in parts:
            cur_subdir = self._set_default_subdir(parent=cur_subdir, name=subdir_name)

        return cur_subdir

    def add_file_by_fullpath(self, fullpath):
        relpath = os.path.relpath(fullpath, self.fullpath())
        self.add_file_by_relpath(relpath)

    def add_file_by_relpath(self, relpath):
        dirpath = os.path.dirname(relpath)
        parent_dir_node = self.create_dir_node_from_relpath_if_not_exists(dirpath)
        filename = os.path.basename(relpath)
        _file = FileEntry(filename, *parent_dir_node.data._child_paths(filename))
        # Rescanning a tree re-adds files it already has
        existing_node = self.get_node(_file.relpath)
        if existing_node is not None:
            return existing_node.data
        file_entry = self._create_node_orig(
            identifier=_file.relpath,
            tag=_file.name,
            data=_file,
            parent=parent_dir_node)
        return file_entry.data

    def iter_files(self):
        for node in self.nodes.values():
            if isinstance(node.data, FileEntry):
                yield node.data

    def does_dir_contain_any_files(self):
        return next(self.iter_files(), None) is not None

    def get_unknown_entries_in_given_dirtree(self, other):
        unknown_files_dirtree = DirTree(other._rootpath)
        for file_entry in other.iter_files():
            if file_entry.relpath not in self.nodes:
                unknown_files_dirtree.add_file_by_relpath(file_entry.relpath)
        return unknown_files_dirtree

    def fullpath(self):
        return self._rootpath

    def _set_default_subdir(self, parent, name):
        relpath, fullpath = parent.data._child_paths(name)
        node = self.get_node(relpath)
        if node is None:
            node = self._create_node_orig(
                identifier=relpath,
                tag=name,
                data=DirEntry(name, relpath, fullpath),
                parent=parent.identifier)
        return node

    def _create_node_override_method(self, *_, **__):
        raise NotImplementedError('Please use create_dir_node_from_fullpath_if_not_exists, '
            'add_file_by_relpath, or add_file_by_fullpath')

