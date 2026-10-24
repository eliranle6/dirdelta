import os

import treelib

from dirdelta import entries


class DirTree(object):
    """A tree of a dir's files and dirs: each node's data is its entry (DirEntry or FileEntry), and
    its id is the entry's relpath (the root's is '').

    It holds a treelib.Tree, rather than being one, so nodes are only added through its own methods
    (add_file_by_relpath() and the like), which keep the entries' paths consistent.
    """
    @classmethod
    def from_file_entries(cls, files, filesystem_dirpath):
        """A DirTree rooted at filesystem_dirpath holding the given files, at the same relative paths."""
        tree = cls(os.path.realpath(filesystem_dirpath))
        for file_entry in files:
            tree.add_file_by_relpath(file_entry.relpath)
        return tree

    def __init__(self, rootpath, silent=False):
        self._silent = silent

        rootpath = rootpath.rstrip('/') or '/'
        self._rootpath = rootpath
        self._tree = treelib.Tree()
        root = entries.DirEntry(name='/', relpath='', fullpath=self._rootpath)
        self._root = self._tree.create_node(identifier='', tag=root.name, data=root)

    # The tree's nodes (treelib.Node: identifier, tag, data)

    @property
    def root(self):
        """The root's id"""
        return self._tree.root

    def get_node(self, identifier):
        """The node with the id, or None"""
        return self._tree.get_node(identifier)

    def children(self, identifier):
        return self._tree.children(identifier)

    def all_nodes(self):
        return self._tree.all_nodes()

    def remove_node(self, identifier):
        """Remove the node and the nodes under it"""
        self._tree.remove_node(identifier)

    def __contains__(self, identifier):
        return self._tree.contains(identifier)

    def __len__(self):
        return len(self._tree)

    def create_dir_node_from_fullpath_if_not_exists(self, fullpath):
        # Convert to relative path
        relpath = os.path.relpath(fullpath, self.fullpath())

        return self.create_dir_node_from_relpath_if_not_exists(relpath)

    def create_dir_node_from_relpath_if_not_exists(self, relpath):
        # Make sure all subdires have nodes ('' and '.' are the root itself)
        if relpath in ('', '.'):
            return self._root
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
        _file = entries.FileEntry(filename, *parent_dir_node.data._child_paths(filename))
        # Rescanning a tree re-adds files it already has
        existing_node = self.get_node(_file.relpath)
        if existing_node is not None:
            return existing_node.data
        file_entry = self._tree.create_node(
            identifier=_file.relpath,
            tag=_file.name,
            data=_file,
            parent=parent_dir_node)
        return file_entry.data

    def iter_files(self):
        for node in self._tree.all_nodes_itr():
            if isinstance(node.data, entries.FileEntry):
                yield node.data

    def does_dir_contain_any_files(self):
        return next(self.iter_files(), None) is not None

    def get_unknown_entries_in_given_dirtree(self, other):
        unknown_files_dirtree = DirTree(other._rootpath)
        for file_entry in other.iter_files():
            if file_entry.relpath not in self:
                unknown_files_dirtree.add_file_by_relpath(file_entry.relpath)
        return unknown_files_dirtree

    def fullpath(self):
        return self._rootpath

    def _set_default_subdir(self, parent, name):
        relpath, fullpath = parent.data._child_paths(name)
        node = self.get_node(relpath)
        if node is None:
            node = self._tree.create_node(
                identifier=relpath,
                tag=name,
                data=entries.DirEntry(name, relpath, fullpath),
                parent=parent.identifier)
        return node

