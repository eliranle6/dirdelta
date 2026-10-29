import collections
import os

import treelib

from dirdelta import dryrun
from dirdelta import entries
from dirdelta import messages


class DirTree(object):
    """A tree of a dir's files and dirs: each node's data is its entry (DirEntry or FileEntry), and
    its id is the entry's relpath (the root's is '').

    It holds a treelib.Tree, rather than being one, so nodes are only added through its own methods
    (add_file_by_relpath() and the like), which keep the entries' paths consistent.

    A tree of a place that files can be copied into and removed from has _copy_file() and
    _remove_file(), for copy_inner_entries_from_dirtree() and remove_files(), and fetch_file(), to
    copy its files elsewhere. One that copies or removes several files at once has _copy_files()
    or _remove_files() too, and one with something to say before a copy from it or a removal
    (in the confirmation) has copy_notes() or removal_notes().
    """
    # What remove_files() says about the removed files' fate, after "removed N of M files from X"
    REMOVED_TO = ""

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

    def copy_inner_entries_from_dirtree(self, dirtree, source=None):
        """Copy dirtree's files into this tree's dir, at the same relative paths, and add them to
        the tree (so the next diff doesn't list them): from source (a tree, by its fetch_file()), or
        else from their entries' full paths on the local disk. A dry run changes neither."""
        files = list(dirtree.iter_files())
        # In a dry run nothing changes: no files or dirs, and not the tree
        verb = "Dry run, not copying" if dryrun.DRYRUN else "Copying"
        nr_started = nr_copied = 0
        is_stopped = False

        def starting(file_entry):
            nonlocal nr_started
            nr_started += 1
            messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, nr_started, len(files)))

        def copied(is_copied):
            nonlocal nr_copied
            nr_copied += bool(is_copied)

        try:
            if dryrun.DRYRUN:
                for file_entry in files:
                    starting(file_entry)
                    copied(True)
            else:
                self._copy_files(files, source, starting, copied)
        except KeyboardInterrupt:
            messages.note_stopped()
            is_stopped = True
        ended = "stopped" if is_stopped else "complete"
        if dryrun.DRYRUN:
            messages.print_line("Dry run %s: nothing was copied to %s (DRYRUN=0 copies)" % (ended, self.displayname()))
        else:
            messages.print_line("Copy %s: copied %d of %d files to %s" % (ended, nr_copied, len(files),
                                                                        self.displayname()))

    def remove_files(self, file_entries):
        """Remove the files, and drop them from the tree (so the next diff doesn't list them). A dry
        run changes neither."""
        verb = "Dry run, not removing" if dryrun.DRYRUN else "Removing"
        nr_started = nr_removed = 0
        is_stopped = False

        def starting(what, nr_files=1):
            """Say that removing what starts: a file, or e.g. a folder of nr_files of the files"""
            nonlocal nr_started
            nr_started += nr_files
            messages.print_line("%s %s (%d out of %d)" % (verb, what, nr_started, len(file_entries)))

        def removed(nr_files=1):
            nonlocal nr_removed
            nr_removed += nr_files

        try:
            self._remove_files(file_entries, starting, removed)
        except KeyboardInterrupt:
            messages.note_stopped()
            is_stopped = True
        ended = "stopped" if is_stopped else "complete"
        if dryrun.DRYRUN:
            messages.print_line("Dry run %s: nothing was removed from %s (DRYRUN=0 removes)" % (ended,
                                                                                          self.displayname()))
        else:
            messages.print_line("Remove %s: removed %d of %d files from %s%s" % (
                ended, nr_removed, len(file_entries), self.displayname(), self.REMOVED_TO))

    def _copy_files(self, files, source, starting, copied):
        """Copy the files (see _copy_file()), calling starting(file_entry) as each one's copy
        starts, and copied(whether it was copied) as it ends. One at a time, unless a tree does it
        otherwise."""
        for file_entry in files:
            starting(file_entry)
            copied(self._copy_file(file_entry, source))

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files (see _remove_file()), or in a dry run only say so, calling
        starting(what, nr_files) as removing each one (or some together) starts, and
        removed(nr_files) for those removed. One at a time, unless a tree does it otherwise."""
        for file_entry in file_entries:
            starting(file_entry)
            if dryrun.DRYRUN or self._remove_file(file_entry):
                removed()

    def copy_notes(self, relpaths):
        """Lines for the confirmation of copying the files at relpaths out of this tree"""
        return []

    def removal_notes(self, relpaths):
        """Lines for the confirmation of removing the files at relpaths"""
        return []

    def cant_fetch(self, relpath):
        """Why the file at relpath can't be copied out (fetch_file()), or None if it can"""
        return None

    def _copy_file(self, file_entry, source):
        """Copy file_entry (of another tree, from source, if given) into this tree, at the same
        relative path. Returns whether it was copied."""
        raise NotImplementedError("Can't copy files to %s" % (self.displayname(),))

    def _remove_file(self, file_entry):
        """Remove file_entry, and its node. Returns whether it was removed."""
        raise NotImplementedError("Can't remove files from %s" % (self.displayname(),))

    def fetch_file(self, relpath, local_path):
        """Copy the file at relpath to local_path, on the local disk"""
        raise NotImplementedError("Can't copy files from %s" % (self.displayname(),))

    def iter_files(self):
        for node in self._tree.all_nodes_itr():
            if isinstance(node.data, entries.FileEntry):
                yield node.data

    def file_size(self, relpath):
        """The size in bytes of the file at relpath, or None if it isn't known"""
        return None

    # How many files files_by_name() goes through between its progress() calls
    FILES_PER_PROGRESS = 1000

    def files_by_name(self, progress=None):
        """{name: [(relpath, size)]} of all the tree's files (size: as file_size()), to find where
        it has a file of a name. progress, if given, is called now and then with how many files
        it has so far (and may raise, to stop it)."""
        found = collections.defaultdict(list)
        for count, file_entry in enumerate(self.iter_files(), 1):
            found[os.path.basename(file_entry.relpath)].append(
                (file_entry.relpath, self.file_size(file_entry.relpath)))
            if progress is not None and count % self.FILES_PER_PROGRESS == 0:
                progress(count)
        return found

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

