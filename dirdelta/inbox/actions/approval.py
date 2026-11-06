"""The approval of a move or copy: the tree it makes, shown before it's done"""
import os
import posixpath

from dirdelta.claude import ai
from dirdelta.inbox.constants import LABEL
from dirdelta.inbox.formatting import files_text, join_path, wrapped
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


class Approval(object):
    """Approving moves (InboxSort's)"""

    def _approve(self, action, plan, is_reviewed=False):
        """Show where each file of plan (relpath, its path in the sorted tree: a dir and a name, maybe
        another) goes, as the tree it makes (unless is_reviewed: it was), then, once the user confirms,
        move (MOVE_TO) or copy them there. Returns the picked files done (or that would have been, in a
        dry run), or None if the user didn't confirm."""
        verb = "Move" if action == self.MOVE_TO else "Copy"
        targets = {}
        for relpath, target in plan:
            targets.setdefault(target, []).append(relpath)
        clashes = {target: sources for target, sources in targets.items() if len(sources) > 1}
        if clashes:
            target = sorted(clashes)[0]
            messages.show("Files of the same name",
                          ["%d files would go to %s: %s. Pick them apart." %
                           (len(clashes[target]), join_path(self.root_path, target), ', '.join(clashes[target]))],
                          dryrun.label(), 'red')
            return None
        destinations = sorted({os.path.dirname(target) for _, target in plan})
        new_dirs = [destination for destination in destinations
                    if not self._root_tree.exists(destination)]
        previews = {}
        for target, (relpath,) in targets.items():
            lines = ["From: %s" % (posixpath.join(self.inbox_path, relpath),)]
            if self._root_tree.exists(target):
                lines += ["", "There's a file there already:", "it's skipped."]
            if os.path.dirname(target) in new_dirs:
                lines += ["", "In a new dir."]
            if os.path.basename(target) != os.path.basename(relpath):
                lines += ["", "Renamed, from:"] + wrapped(os.path.basename(relpath), "  ")
            recommendation = self._recommendations.get(relpath)
            if recommendation and self._target(relpath) == target:
                lines += ["", "Why (Claude):"] + wrapped(recommendation.get('reason', ''), "  ")
            previews[target] = lines
        summary = ("%s %s from %s into %d dirs of %s%s" %
                   (verb, files_text(len(plan)), self.inbox_path, len(destinations), self.root_path,
                    " (%d of them new)" % (len(new_dirs),) if new_dirs else ""))
        header = "%s, where shown (beside each: where it's from). Look them through." % (summary,)
        if not is_reviewed and not picker.view_files(self.root_path, sorted(targets, key=lambda target: target.split('/')),
                                 header=header, previews=previews, label=LABEL,
                                 key_hints=[('Enter', 'go on to say yes or no'), ('q', 'back to the inbox')]):
            return None
        lines = [summary + "?"]
        if not self.is_same_kind:
            lines.append("(%s %s, then %s from the inbox%s, once each is there.)" % (
                "Uploaded to Google Drive" if self.root_is_cloud else "Downloaded from Google Drive",
                "and removed" if action == self.MOVE_TO else "", "" if action == self.MOVE_TO else "kept in",
                " (to Drive's trash)" if self.inbox_is_cloud and action == self.MOVE_TO else ""))
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, LABEL):
            return None
        moves = list(plan)
        # The cache's keys of each file, here and where it goes (the same size), while it's here
        sizes = {relpath: self._size(relpath) for relpath, _ in plan}
        keys = {relpath: (self._path_key(relpath, sizes[relpath]),
                          ai.path_key(posixpath.join(self.root_path, target), sizes[relpath]))
                for relpath, target in plan}
        # Once it's done (or stopped), Enter goes back to the picker, so what was done can be read
        done = None
        with messages.progress_screen(summary + (" (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock:
            if self.is_same_kind:
                done = (self._inbox_tree.move_files(moves, self._root_tree) if action == self.MOVE_TO else
                        self._inbox_tree.copy_files_within(moves, self._root_tree))
            else:
                done = self._transfer(moves, action == self.MOVE_TO)
        if dryrun.DRYRUN:
            return [relpath for relpath, _ in plan]
        if done is None:
            # Stopped (Ctrl-C) before it said: the ones in the sorted tree now (and, moved, out of
            # the inbox; one copied but not removed yet is still the inbox's)
            done = [(relpath, new_relpath) for relpath, new_relpath in moves if self._root_tree.has_file(new_relpath)
                    and (action != self.MOVE_TO or not self._inbox_tree.has_file(relpath))]
        done_sources = {relpath for relpath, _ in done}
        done = [relpath for relpath, _ in plan if relpath in done_sources]
        # What Claude said of each goes with it, to its new path
        ai.carry(dict(keys[relpath] for relpath in done))
        if action == self.MOVE_TO:
            # Only the sorted tree's log says so: files leaving the inbox for it is what an inbox is
            # for, not a change of the inbox to keep in its own log
            self.changes.note(self.root_path, 'added', len(done), self.inbox_path)
        else:
            self.changes.note(self.root_path, 'copied', len(done), self.inbox_path)
        not_done = [relpath for relpath, _ in plan if relpath not in set(done)]
        if not_done:
            self._say_not_done("moved" if action == self.MOVE_TO else "copied", not_done, len(plan))
        return done
