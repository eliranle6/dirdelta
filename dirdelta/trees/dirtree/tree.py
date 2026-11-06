"""DirTree: a tree of a dir's files and dirs; what it does with them are mixins, each in a module here"""
import os

import treelib

from dirdelta.trees import entries
from dirdelta.trees.dirtree.changes import Changes
from dirdelta.trees.dirtree.copying import Copying
from dirdelta.trees.dirtree.dir_moves import DirMoves
from dirdelta.trees.dirtree.files_info import FilesInfo
from dirdelta.trees.dirtree.listeners import Listeners


class DirTree(Listeners, Copying, Changes, DirMoves, FilesInfo):

    """A tree of a dir's files and dirs: each node's data is its entry (DirEntry or FileEntry), and
    its id is the entry's relpath (the root's is '').

    It holds a treelib.Tree, rather than being one, so nodes are only added through its own methods
    (add_file_by_relpath() and the like), which keep the entries' paths consistent.

    A tree of a place that files can be copied into, removed from and moved in has _copy_file(),
    _remove_file() and _move_file(), for copy_inner_entries_from_dirtree(), remove_files() and
    move_files(), and fetch_file(), to copy its files elsewhere. One that copies or removes several files at once has _copy_files()
    or _remove_files() too, and one with something to say before a copy from it or a removal
    (in the confirmation) has copy_notes() or removal_notes().
    """
    # What remove_files() says about the removed files' fate, after "removed N of M files from X"
    REMOVED_TO = ""
    # Whether copying a file in where it has one already replaces that one (see replacing())
    _is_replacing = False

    @classmethod
    def from_file_entries(cls, files, filesystem_dirpath):
        """A DirTree rooted at filesystem_dirpath holding the given files, at the same relative paths."""
        tree = cls(os.path.realpath(filesystem_dirpath))
        for file_entry in files:
            tree.add_file_by_relpath(file_entry.relpath)
        return tree

    def __init__(self, rootpath, silent=False):
        self._silent = silent
        # What's told of each file changed (see add_listener())
        self._listeners = []
        # The dirs (relpaths) never removed, nor moved whole, nor trashed whole (keep_dirs())
        self._kept_dirs = set()

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

    def get_unknown_entries_in_given_dirtree(self, other):
        unknown_files_dirtree = DirTree(other._rootpath)
        for file_entry in other.iter_files():
            if file_entry.relpath not in self:
                unknown_files_dirtree.add_file_by_relpath(file_entry.relpath)
        return unknown_files_dirtree

    def fullpath(self):
        return self._rootpath

    def displayname(self):
        """The replica's name for the screens: its path, as given (a cloud tree's says it's one)"""
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
