"""Moving, copying and removing the inbox's files"""
import contextlib
import os
import posixpath

from dirdelta.claude import ai
from dirdelta.inbox.constants import LABEL
from dirdelta.inbox.formatting import files_text, join_path
from dirdelta.inbox.listing import tree_of
from dirdelta.trees import entries
from dirdelta.ui import filescreen
from dirdelta.ui import messages
from dirdelta.util import dryrun
from dirdelta.util import text


class Transfer(object):
    """Doing the moves (InboxSort's)"""

    def _move_in_inbox(self, relpaths, destination):
        """Move the inbox's files at relpaths to its dir at destination (a relpath in it), under their
        own names, once the user confirms; what's known of them goes with them. Returns the ones
        moved (in a dry run, the ones it would move), or None if none were."""
        plan = [(relpath, join_path(destination, posixpath.basename(relpath))) for relpath in relpaths
                if posixpath.dirname(relpath) != destination]
        where = join_path(self.inbox_path, destination)
        if not plan:
            messages.show("Can't move them there", ["%s/ has them already." % (where,)], dryrun.label(), 'red')
            return None
        return self._move_plan_in_inbox(plan, where)

    def _move_plan_in_inbox(self, plan, where):
        """Move the inbox's files, each of plan (relpath, its new one in the inbox), to where (what to
        call it), once the user confirms; what's known of them goes with them. Returns the ones moved
        (in a dry run, the ones it would move), or None if none were."""
        there = [target for _, target in plan if self._inbox_tree.exists(target)]
        if there:
            messages.show("Can't move them there",
                          ["%s/ has a file or dir of the same name already:" % (where,)] +
                          ["  " + target for target in there[:filescreen.MAX_FILES_LISTED]],
                          dryrun.label(), 'red')
            return None
        lines = ["Move %s to %s/?" % (files_text(len(plan)), where)]
        lines += text.listed(["  " + relpath for relpath, _ in plan], filescreen.MAX_FILES_LISTED)
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, LABEL):
            return None
        # Stopped (Ctrl-C) before move_files() says (it says how far it got, if it's stopped in it)
        done = []
        with messages.progress_screen("Moving %s in %s%s" % (files_text(len(plan)), self.inbox_path,
                                                             " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock:
            done = self._inbox_tree.move_files([(relpath, target) for relpath, target in plan])
        if dryrun.DRYRUN:
            return [relpath for relpath, _ in plan]
        moved = {relpath: new for relpath, new in done}
        self._carry(moved)
        not_done = [relpath for relpath, _ in plan if relpath not in moved]
        if not_done:
            self._say_not_done("moved", not_done, len(plan))
        return list(moved) or None

    def _say_not_done(self, what, relpaths, count):
        """Show that the inbox's files at relpaths (of count) weren't moved, copied or removed (what)"""
        messages.show("Not all were %s" % (what,),
                      ["%d of the %s couldn't be %s (they're still in %s):" % (
                          len(relpaths), files_text(count), what, self.inbox_path)] +
                      text.listed(["  " + relpath for relpath in relpaths], filescreen.MAX_FILES_LISTED),
                      dryrun.label(), 'red')

    def _target(self, relpath):
        """Where Claude recommends the inbox's file at relpath go, in the sorted tree"""
        return ai.recommended_path(self._recommendations[relpath])

    def _transfer(self, moves, is_move):
        """Copy the inbox's files to the sorted tree, of another kind, each of moves (relpath in the
        inbox's tree, relpath in the sorted tree's): an upload to Drive, or a download from it, as a
        sync's copy does; then if is_move, remove from the inbox the ones copied. Returns the moves
        done (none in a dry run)."""
        source_of = {new_relpath: relpath for relpath, new_relpath in moves}
        files = [entries.FileEntry(os.path.basename(new_relpath), new_relpath,
                                   os.path.join(self.inbox_path, relpath))
                 for relpath, new_relpath in moves]
        source = None if self.root_is_cloud else _Renamed(self._inbox_tree, source_of)
        # (Each uploaded from its own path in the inbox, not from its relpath in the sorted tree)
        self._root_tree.copy_in(files, source)
        if dryrun.DRYRUN:
            if is_move:
                self._inbox_tree.remove_files(self._entries(relpath for relpath, _ in moves))
            return []
        done = [(relpath, new_relpath) for relpath, new_relpath in moves if self._root_tree.has_file(new_relpath)]
        if is_move and done:
            self._inbox_tree.remove_files(self._entries(relpath for relpath, _ in done))
            done = [(relpath, new_relpath) for relpath, new_relpath in done
                    if not self._inbox_tree.has_file(relpath)]
        return done

    def log_trees(self):
        """[(tree, path)] of the sorted tree, a tree of its own (as it is now: a Drive one from the
        cache), to read and write its log (see replicalog.py); an inbox has none"""
        return [(tree_of(self.root_path), self.root_path)]

    def _entries(self, relpaths):
        """The entries of the inbox's files at relpaths (in its tree), to remove them"""
        found = []
        for relpath in relpaths:
            node = self._inbox_tree.get_node(relpath)
            found.append(node.data if node is not None else entries.FileEntry(
                os.path.basename(relpath), relpath, os.path.join(self._inbox_tree.fullpath(), relpath)))
        return found

    def _remove(self, relpaths, listed=None, to_trash=False):
        """Remove the inbox's files at relpaths, once the user confirms twice; listed: the lines that
        list them (else their relpaths). With to_trash, a local inbox's go to the desktop's trash
        (Drive's go to its trash anyway), rather than for good."""
        lines = ["Remove %s from %s?" % (files_text(len(relpaths)), self.inbox_path)]
        listed = listed or ["  %s" % (relpath,) for relpath in relpaths]
        lines += text.listed(listed, filescreen.MAX_FILES_LISTED)
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, LABEL):
            return None
        if not self._is_sure(len(relpaths), self.inbox_path, self.inbox_is_cloud, to_trash, LABEL):
            return None
        file_entries = self._entries(relpath for relpath in relpaths)
        # Once it's done (or stopped), Enter goes back to the picker, so what was removed can be read
        with messages.progress_screen("Removing %s from %s%s" % (files_text(len(relpaths)), self.inbox_path,
                                                                " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock, \
                (self._inbox_tree.trashing() if to_trash and not self.inbox_is_cloud else contextlib.nullcontext()):
            self._inbox_tree.remove_files(file_entries)
        if dryrun.DRYRUN:
            return relpaths
        kept = [relpath for relpath in relpaths if self._is_in_inbox_now(relpath)]
        if kept:
            self._say_not_done("removed", kept, len(relpaths))
        return [relpath for relpath in relpaths if relpath not in set(kept)]

    def _is_in_inbox_now(self, relpath):
        """Whether the inbox has a file at relpath (asked of just it: listing a big inbox takes long)"""
        if self.inbox_is_cloud:
            return relpath in self._inbox_tree
        return os.path.lexists(os.path.join(self.inbox_path, relpath))


class _Renamed(object):
    """A tree to copy from (a copy_in() source) whose files are asked for by
    where they go (relpaths in the tree copied into), each where source_of says it is in tree"""
    def __init__(self, tree, source_of):
        self._tree = tree
        self._source_of = source_of

    def cant_fetch(self, relpath):
        return self._tree.cant_fetch(self._source_of[relpath])

    def fetch_file(self, relpath, local_path):
        self._tree.fetch_file(self._source_of[relpath], local_path)
