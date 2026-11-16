"""Copying what a sort put into the sorted tree into the other replicas of it the user picked (see
choice.py): only where they lack it, never over a file there already"""
import os

from dirdelta.inbox.formatting import files_text
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from dirdelta.util import dryrun
from dirdelta.util import text


# How many of the files left as they were (a different one there) are listed
MAX_LISTED = 10


class Followers(object):
    """The other replicas of the sorted tree at root_path (its tree, root_tree) at paths, each copied
    into from it, its changes noted in changes (a log_entries.Changes); a collaborator of InboxSort's"""

    def __init__(self, root_path, root_tree, paths, changes, tree_of):
        self._root_path = root_path
        self._root_tree = root_tree
        self.paths = list(paths)
        self._changes = changes
        # {path: its tree}, each made once it's needed (a Drive one from the cache)
        self._trees = {}
        self._tree_of = tree_of

    def trees(self):
        """[(tree, path)] of each, for its log (see replicalog.py)"""
        return [(self._tree(path), path) for path in self.paths]

    def confirmation_lines(self):
        """What the confirmation of a move or copy into the sorted tree says of them (none if none)"""
        if not self.paths:
            return []
        return ["(Then copied into %s too, where it lacks them.)" % (', '.join(self.paths),)]

    def bring(self, files):
        """Copy the sorted tree's files into each of them that lacks them, on a progress screen: each of
        files is (its relpath in the sorted tree, its size, its SHA-1 if known, else None), as it is or
        (in a dry run) would be there. A file one has already, of another size or hash, is left as it
        is, and said."""
        if not self.paths or not files:
            return
        title = "Copying %s into the other replicas of %s%s" % (files_text(len(files)), self._root_path,
                                                                 " (a dry run)" if dryrun.DRYRUN else "")
        with messages.progress_screen(title, dryrun.label()):
            for path in self.paths:
                self._bring_to(path, files)

    def _bring_to(self, path, files):
        tree = self._tree(path)
        missing, same, different = [], [], []
        for relpath, size, sha1 in files:
            if not _exists(tree, relpath):
                missing.append(relpath)
            elif _is_same(tree, relpath, size, sha1):
                same.append(relpath)
            else:
                different.append(relpath)
        messages.print_line("%s: %d to copy%s" % (path, len(missing), ", %d there already" % (len(same),) if same else ""))
        if different:
            messages.print_line("Left as they are, a different file there (a sync of the two shows them):", 'yellow')
            for line in text.listed(["  " + relpath for relpath in different], MAX_LISTED):
                messages.print_line(line, 'yellow')
        if not missing:
            return
        # From the sorted tree: a Drive one's files fetched from it, a local one's read where they are
        source = None if localdiskdirtree.is_local(self._root_tree) else self._root_tree
        tree.copy_in([entries.FileEntry(os.path.basename(relpath), relpath, os.path.join(self._root_path, relpath))
                      for relpath in missing], source)
        if not dryrun.DRYRUN:
            self._changes.note(path, 'copied', sum(1 for relpath in missing if _exists(tree, relpath)), self._root_path)

    def _tree(self, path):
        if path not in self._trees:
            self._trees[path] = self._tree_of(path)
        return self._trees[path]


def _exists(tree, relpath):
    """Whether the tree has a file or dir at relpath (a local one's asked of the disk: it isn't scanned)"""
    if localdiskdirtree.is_local(tree):
        return os.path.lexists(os.path.join(tree.fullpath(), relpath))
    return tree.exists(relpath)


def _is_same(tree, relpath, size, sha1):
    """Whether the tree's file at relpath is the one of size and sha1 (if known): the same size, and
    the same hash where both are known"""
    if tree.file_size(relpath) != size:
        return False
    there = tree.known_hash(relpath, 'sha1')
    return there is None or sha1 is None or there == sha1
