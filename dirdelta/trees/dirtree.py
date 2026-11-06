import collections
import contextlib
import os

import treelib

from dirdelta.util import dryrun
from dirdelta.trees import entries
from dirdelta.ui import messages
from dirdelta.trees import paths


class HashStopped(Exception):
    """Raised by content_hash() (and elsewhere's comparing) when its should_stop() says to"""


def _verb(verb):
    """A batch's verb before each file, e.g. 'Copying', or in a dry run 'Dry run, not copying'"""
    return "Dry run, not %s" % (verb,) if dryrun.DRYRUN else verb.capitalize()


class DirTree(object):
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

    def add_listener(self, listener):
        """From now on, listener is told of each file dirdelta makes, removes or moves here: its
        add(relpath, size), remove(relpath) and move(relpath, new_relpath) are called (e.g. an
        elsewhere.Index's), once it's done; not in a dry run"""
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    def _tell_added(self, relpath):
        if self._listeners:
            size = self.file_size(relpath)
            for listener in self._listeners:
                listener.add(relpath, size)

    def _tell_removed(self, relpath):
        for listener in self._listeners:
            listener.remove(relpath)

    def _tell_moved(self, relpath, new_relpath, to):
        """The file was moved to new_relpath in to (maybe this tree)"""
        if to is self:
            for listener in self._listeners:
                listener.move(relpath, new_relpath)
        else:
            self._tell_removed(relpath)
            to._tell_added(new_relpath)

    def keep_dirs(self, relpaths):
        """Never remove the dirs at relpaths when a removal or a move leaves them empty, nor move
        or remove one, or a dir it's in, as a whole (e.g. an inbox, whose files are moved out of it)"""
        self._kept_dirs |= set(relpaths)

    def _is_kept(self, dirpath):
        """Whether the dir at dirpath is kept, or has a kept dir in it"""
        return any(_is_at_or_under(kept, dirpath) for kept in self._kept_dirs)

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
        """copy_in() dirtree's files"""
        self.copy_in(list(dirtree.iter_files()), source)

    def copy_in(self, files, source=None):
        """Copy files (FileEntry's) into this tree's dir, each at its relpath, and add them to the
        tree (so the next diff doesn't list them): from source (a tree, by its fetch_file()), or
        else from their entries' full paths on the local disk (which may be elsewhere than at their
        relpaths, e.g. an inbox's files going to other dirs). A dry run changes neither."""
        files = list(files)
        # In a dry run nothing changes: no files or dirs, and not the tree
        verb = _verb('copying')
        nr_started = nr_copied = 0

        def starting(file_entry):
            nonlocal nr_started
            nr_started += 1
            messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, nr_started, len(files)))

        def copied(is_copied):
            nonlocal nr_copied
            nr_copied += bool(is_copied)

        def work():
            if dryrun.DRYRUN:
                for file_entry in files:
                    starting(file_entry)
                    copied(True)
            else:
                self._copy_files(files, source, starting, copied)
        self._batch(work, ('Copy', 'copied', 'copies', 'to ' + self.displayname()), lambda: nr_copied, len(files))

    @contextlib.contextmanager
    def replacing(self):
        """Inside, copy_in() replaces a file the tree has already at a copy's path (another version
        of it, see differing.py), as a tree of its kind can: a local dir's goes to the desktop's trash,
        a Drive file gets the copy as its new version (Drive keeps the old one). Outside, a tree
        doesn't expect one there."""
        self._is_replacing = True
        try:
            yield
        finally:
            self._is_replacing = False

    def remove_files(self, file_entries):
        """Remove the files, and drop them from the tree (so the next diff doesn't list them). A dry
        run changes neither."""
        verb = _verb('removing')
        nr_started = nr_removed = 0

        def starting(what, nr_files=1):
            """Say that removing what starts: a file, or e.g. a folder of nr_files of the files"""
            nonlocal nr_started
            nr_started += nr_files
            messages.print_line("%s %s (%d out of %d)" % (verb, what, nr_started, len(file_entries)))

        def removed(nr_files=1):
            nonlocal nr_removed
            nr_removed += nr_files

        self._batch(lambda: self._remove_files(file_entries, starting, removed),
                    ('Remove', 'removed', 'removes', 'from ' + self.displayname() + self.REMOVED_TO),
                    lambda: nr_removed, len(file_entries), dry_where='from ' + self.displayname())

    def move_files(self, moves, to=None):
        """Move files within the tree, or to another of its kind (to; a rename there too): each of
        moves is (relpath, new_relpath); a whole dir's, as one (see dir_moves()). Returns the moves
        done. A dry run changes nothing (and returns none)."""
        verb = _verb('moving')
        done = []
        to = to or self
        dir_moves, file_moves = self.dir_moves(moves, to)

        def work():
            for dirpath, new_dirpath, its_moves in dir_moves:
                messages.print_line("%s dir %s/ to %s/, with its %d files" % (verb, dirpath, new_dirpath,
                                                                             len(its_moves)))
                if not dryrun.DRYRUN and self._move_dir(dirpath, new_dirpath, to):
                    done.extend(its_moves)
            for number, (relpath, new_relpath) in enumerate(file_moves, 1):
                messages.print_line("%s %s to %s (%d out of %d)" % (verb, relpath, new_relpath, number,
                                                                    len(file_moves)))
                if not dryrun.DRYRUN and self._move_file(relpath, new_relpath, to):
                    done.append((relpath, new_relpath))

        def after():
            if done:
                self._moved(done)
        self._batch(work, ('Move', 'moved', 'moves', self._where(to)), lambda: len(done), len(moves), after=after)
        return done

    def _where(self, to):
        """Where a move or copy goes, to say it"""
        return 'in ' + self.displayname() if to is self else 'to ' + to.displayname()

    def copy_files_within(self, copies, to=None):
        """Copy files within the tree, or to another of its kind (to): each of copies is (relpath,
        new_relpath). Returns the copies done. A dry run changes nothing (and returns none)."""
        verb = _verb('copying')
        done = []
        to = to or self

        def work():
            for number, (relpath, new_relpath) in enumerate(copies, 1):
                messages.print_line("%s %s to %s (%d out of %d)" % (verb, relpath, new_relpath, number,
                                                                    len(copies)))
                if not dryrun.DRYRUN and self._copy_within(relpath, new_relpath, to):
                    done.append((relpath, new_relpath))
        self._batch(work, ('Copy', 'copied', 'copies', self._where(to)), lambda: len(done), len(copies))
        return done

    def _batch(self, work, words, nr_done, total, after=None, dry_where=None):
        """Run a batch operation's work(), which Ctrl-C stops (it's said, see messages.note_stopped()),
        then after() (if given), then say how it ended, by words: (its noun, its past, its third
        person, where, e.g. ('Copy', 'copied', 'copies', 'to cloud/x')), nr_done() files of total
        (or in a dry run, that nothing was, where dry_where says, if given)"""
        noun, past, third, where = words
        is_stopped = False
        try:
            work()
        except KeyboardInterrupt:
            messages.note_stopped()
            is_stopped = True
        if after is not None:
            after()
        ended = "stopped" if is_stopped else "complete"
        if dryrun.DRYRUN:
            messages.print_line("Dry run %s: nothing was %s %s (DRYRUN=0 %s)" % (ended, past, dry_where or where, third))
        else:
            messages.print_line("%s %s: %s %d of %d files %s" % (noun, ended, past, nr_done(), total, where))

    def _copy_within(self, relpath, new_relpath, to=None):
        """Copy the file at relpath to new_relpath here, or in to, another tree of its kind (where
        there's none), and add its node. Returns whether it was copied (if not, says why)."""
        raise NotImplementedError("Can't copy files within %s" % (self.displayname(),))

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

    def _move_file(self, relpath, new_relpath, to=None):
        """Move the file at relpath to new_relpath here, or in to, another tree of its kind (where
        there's none), and its node. Returns whether it was moved (if not, says why)."""
        raise NotImplementedError("Can't move files in %s" % (self.displayname(),))

    def dir_moves(self, moves, to=None):
        """Of moves (relpath, new_relpath), the ones that move a whole dir: [(dirpath, new_dirpath,
        its moves)], the topmost, each a dir all of whose files (files_under()) are moved into
        new_dirpath (in to, or here) at the same relative paths, where there's nothing yet; and the
        other moves"""
        to = to or self
        new_of = dict(moves)
        pairs = set()
        for relpath, new_relpath in moves:
            path, new_path = relpath.split('/'), new_relpath.split('/')
            # The dirs above both whose paths below them are the same
            depth = 1
            while depth < len(path) and depth < len(new_path) and path[-depth:] == new_path[-depth:]:
                pairs.add(('/'.join(path[:-depth]), '/'.join(new_path[:-depth])))
                depth += 1
        found = []
        for dirpath, new_dirpath in sorted(pairs, key=lambda pair: (pair[0].count('/'), pair)):
            if (any(_is_at_or_under(dirpath, other) for other, _, _ in found) or self._is_kept(dirpath) or
                    (to is self and (_is_at_or_under(new_dirpath, dirpath) or _is_at_or_under(dirpath, new_dirpath)))):
                continue
            files = self.files_under(dirpath)
            if (files and not to.exists(new_dirpath) and
                    all(new_of.get(relpath) == new_dirpath + relpath[len(dirpath):] for relpath in files)):
                found.append((dirpath, new_dirpath, [(relpath, new_of[relpath]) for relpath in files]))
        in_dirs = {relpath for _, _, its_moves in found for relpath, _ in its_moves}
        return found, [move for move in moves if move[0] not in in_dirs]

    def files_under(self, dirpath):
        """The relpaths of what's under the dir at dirpath that isn't a dir (none if it isn't one)"""
        node = self.get_node(dirpath)
        if node is None or not isinstance(node.data, entries.DirEntry):
            return []
        return [node.identifier for node in self._tree.subtree(dirpath).all_nodes_itr()
                if isinstance(node.data, entries.FileEntry)]

    def nodes_under(self, dirpath):
        """The nodes at and under dirpath (the dir's, and all in it), each before what's in it"""
        return list(self._tree.subtree(dirpath).all_nodes_itr())

    def exists(self, relpath):
        """Whether there's a file or dir at relpath"""
        return relpath in self

    def _move_dir(self, dirpath, new_dirpath, to=None):
        """Move the dir at dirpath, and all in it, to new_dirpath here, or in to, another tree of its
        kind (where there's nothing), and its nodes. Returns whether it was moved (if not, says why)."""
        raise NotImplementedError("Can't move dirs in %s" % (self.displayname(),))

    def _move_subtree(self, dirpath, new_dirpath, to=None):
        """Move the nodes at and under dirpath to new_dirpath, here or in to (if this tree has them).
        Returns the (relpath, new_relpath) of each."""
        to = to or self
        if dirpath not in self:
            return []
        nodes = [(node.identifier, isinstance(node.data, entries.FileEntry))
                 for node in self._tree.subtree(dirpath).all_nodes_itr()]
        self.remove_node(dirpath)
        moved = []
        # Each dir before what's in it
        for relpath, is_file in sorted(nodes, key=lambda node: node[0].count('/')):
            new_relpath = new_dirpath + relpath[len(dirpath):]
            if is_file:
                to.add_file_by_relpath(new_relpath)
            else:
                to.create_dir_node_from_relpath_if_not_exists(new_relpath)
            moved.append((relpath, new_relpath))
        return moved

    def _moved(self, moves):
        """After move_files() did the moves (relpath, new_relpath), e.g. to tidy the dirs they left"""

    def cant_change(self, relpath):
        """Why what's at relpath can't be moved or renamed in its dir, whatever it is, or None if it
        can (see cant_move())"""
        return None

    def cant_move(self, relpath):
        """Why the file at relpath can't be moved (move_files()), or None if it can"""
        return None

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

    def date_taken(self, relpath):
        """When the photo at relpath was taken ('YYYY-MM-DD HH:MM:SS'), or None if it isn't one, or
        that isn't known"""
        return None

    def content_hash(self, relpath, algorithm, should_stop=None):
        """The hash (hex) of the contents of the file at relpath by algorithm (a hashlib name, e.g.
        'sha1'), or None if it isn't known (or it can't be read). One that has to read the file
        calls should_stop() as it goes, and raises HashStopped once it says to."""
        return None

    def content_hashes(self, relpath, algorithms, should_stop=None):
        """{algorithm: content_hash()} of the algorithms (one read of the file, for one that reads
        it)"""
        return {algorithm: self.content_hash(relpath, algorithm, should_stop) for algorithm in algorithms}

    def known_hash(self, relpath, algorithm):
        """The file's hash (hex) by algorithm if it's known without reading it (Drive's, or one kept
        in the hash cache), else None"""
        return None

    def listed(self, algorithm):
        """{relpath: (size, its hash by algorithm if it's known without reading it, else None)} of all
        its files, at once (a local one's in one listing and one query, not one of each per file)"""
        return {file_entry.relpath: (self.file_size(file_entry.relpath), self.known_hash(file_entry.relpath, algorithm))
                for file_entry in self.iter_files()}

    def known_hashes(self, relpath):
        """The algorithms whose hashes of the file at relpath are known without reading it (e.g.
        Drive's), the best first"""
        return ()

    def local_path(self, relpath):
        """The file's path on the local disk, if it's there (to read it), or None"""
        return None

    def modified_time(self, relpath):
        """When the file at relpath was last modified (seconds since the epoch), or None if that
        isn't known"""
        return None

    def has_file(self, relpath):
        """Whether there's a file at relpath (e.g. after copying it here, or removing it)"""
        node = self.get_node(relpath)
        return node is not None and isinstance(node.data, entries.FileEntry)

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


# One answer for all (see paths.is_at_or_under()): the root has all
_is_at_or_under = paths.is_at_or_under
