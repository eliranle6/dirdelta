"""Renaming files to where the other replica has them (see elsewhere.py)"""
import os

from dirdelta.matching import elsewhere
from dirdelta.sync import replica_ops
from dirdelta.trees import entries
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text


class Renames(object):
    """Renames (InteractiveDirSync's)"""

    def _cant_rename(self, replica, count):
        if not replica_ops.is_writable(replica):
            return "can't: it's read-only"
        if not count:
            return "none of these may be there, moved or renamed"
        return None

    def _renames(self, action, relpaths):
        """The moves of a Rename (RENAME_IN_DST or RENAME_IN_SRC, see _rename()) of the picked files
        at relpaths, which may be in dst: their contents compared first, where they weren't (on a
        progress screen, stoppable), so each is moved only if its match is surely it. None if it's
        stopped, or none is (which is said)."""
        to_compare = elsewhere.to_check(relpaths, self._src, self.dst_index, self.checked)
        if to_compare:
            is_stopped = False
            with messages.progress_screen("Comparing the contents of %s with their matches in %s" %
                                          (replica_ops._files(len(to_compare)), self._dst.displayname()),
                                          dryrun.label()):
                try:
                    elsewhere.check_all(to_compare, self._src, self.src_index, self.dst_index, self.checked,
                                        lambda number, count, relpath: messages.print_progress(
                                            "Comparing %d of %d: %s" % (number, count, relpath)))
                except KeyboardInterrupt:
                    messages.note_stopped()
                    is_stopped = True
                else:
                    messages.print_line("")
                    messages.print_line("Compared %s" % (replica_ops._files(len(to_compare)),))
            if is_stopped:
                return None
        renames = elsewhere.sure_matches(relpaths, self._src, self.dst_index, self.checked, self.src_index)
        # Moving dst's matches to the picked files' paths, or the picked files to the matches'
        if action == self.RENAME_IN_DST:
            moves = [(match, relpath) for relpath, match in renames.items() if self._dst.cant_move(match) is None]
        else:
            moves = [(relpath, match) for relpath, match in renames.items() if self._src.cant_move(relpath) is None]
        if not moves:
            messages.show("Nothing to rename",
                          ["None of the %s is surely in %s, moved or renamed%s." %
                           (replica_ops._files(len(relpaths)), self._dst.displayname(),
                            " (their contents were compared)" if to_compare else "")],
                          dryrun.label())
            return None
        return moves

    def _rename(self, action, moves):
        """Move files, each of moves (relpath, new_relpath), in dst (RENAME_IN_DST) or src, once the
        user confirms. Returns the picked files done (or that would have been, in a dry run), or None
        if the user didn't confirm."""
        replica = self._dst if action == self.RENAME_IN_DST else self._src
        # The picked file of each move
        picked_of = {move: move[1] if action == self.RENAME_IN_DST else move[0] for move in moves}
        lines = ["Move %s in %s?" % (replica_ops._files(len(moves)), replica.displayname())]
        # A whole dir's as one, then the rest one by one
        dir_moves, file_moves = replica.dir_moves(moves)
        listed = (["  %s/ -> %s/ (a dir, with its %s, moved as one)" % (dirpath, new_dirpath, replica_ops._files(len(its_moves)))
                   for dirpath, new_dirpath, its_moves in dir_moves] +
                  ["  %s -> %s" % move for move in file_moves])
        lines += text.listed(listed, self.MAX_FILES_LISTED)
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                                    label=self.LABELS[action], title="Sure?")
        if answer != self.CONFIRM_YES:
            return None
        title = "Moving %s in %s" % (replica_ops._files(len(moves)), replica.displayname())
        if dryrun.DRYRUN:
            title += " (a dry run)"
        # Stopped (Ctrl-C) before move_files() says (it says how far it got, if it's stopped in it)
        done = []
        with messages.progress_screen(title, dryrun.label()):
            done = replica.move_files(moves)
        if dryrun.DRYRUN:
            return [picked_of[move] for move in moves]
        self._note(replica, 'moved', len(done))
        return [picked_of[move] for move in done]

    def _file_entry(self, relpath):
        """The entry of src's file at relpath, for copying or removing it"""
        return entries.FileEntry(os.path.basename(relpath), relpath,
                                 os.path.join(self._src.fullpath(), relpath))
