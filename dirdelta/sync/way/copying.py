"""Copying and removing the picked files, and copying back the other replica's versions"""
import contextlib
import os
import posixpath

from dirdelta.matching import differing
from dirdelta.sync import replica_ops
from dirdelta.trees import entries
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text


class _Added(object):
    """A tree's listener (see DirTree.add_listener()) that keeps which files were made (or replaced)"""
    def __init__(self):
        self.relpaths = set()

    def add(self, relpath, size):
        self.relpaths.add(relpath)

    def remove(self, relpath):
        pass

    def move(self, relpath, new_relpath):
        pass


class Copying(object):
    """Copies and removals (InteractiveDirSync's)"""

    def _copy_back(self, relpaths):
        """Copy dst's versions of the files at relpaths (which differ) to src, replacing src's, once
        the user confirms. Returns the ones done (in a dry run, the ones it would have done), or None
        if the user didn't confirm."""
        src_name, dst_name = self._src.screen_name(), self._dst.screen_name()
        lines = (["Copy %s's versions of %s to %s, replacing its?" % (dst_name, replica_ops.files_text(len(relpaths)), src_name)] +
                 text.listed(["  %s" % (relpath,) for relpath in relpaths], self.MAX_FILES_LISTED) +
                 self._dst.copy_notes(relpaths) + [self._replaced_note(self._src, len(relpaths))])
        newer_here = [relpath for relpath in relpaths if differing.newer(self.differs[relpath]) > 0]
        if newer_here:
            lines.append("Careful: %s newer here than in %s, so this replaces %s with an older version." %
                         (replica_ops.files_text(len(newer_here)) + (" is" if len(newer_here) == 1 else " are"), dst_name,
                          "it" if len(newer_here) == 1 else "them"))
        if dryrun.DRYRUN:
            lines.append(dryrun.note())
        if not self._said_yes(lines, self.LABELS[self.COPY_BACK]):
            return None
        self._last_action = self.COPY_BACK
        title = "Copying %s from %s to %s" % (replica_ops.files_text(len(relpaths)), dst_name, src_name)
        if dryrun.DRYRUN:
            title += " (a dry run)"
        files = [entries.FileEntry(os.path.basename(relpath), relpath, os.path.join(self._dst.fullpath(), relpath))
                 for relpath in relpaths]
        added = _Added()
        self._src.add_listener(added)
        try:
            with messages.progress_screen(title, dryrun.label()), self._src.replacing():
                self._src.copy_in(files, self._dst)
        finally:
            self._src.remove_listener(added)
        if dryrun.DRYRUN:
            return relpaths
        done = [relpath for relpath in relpaths if relpath in added.relpaths]
        self._note(self._src, 'copied', len(done), dst_name)
        return done

    def _replaced_note(self, replica, count):
        """A confirmation's line of what happens to the replica's count versions replaced"""
        if replica_ops.is_local(replica):
            where = replica_ops.discarded_to(replica)
        else:
            where = "kept by Drive as an older version"
        return "%s's versions of %s are replaced (%s)." % (replica.screen_name(), "it" if count == 1 else "the " + replica_ops.files_text(count), where)

    def _copy_elsewhere(self, relpaths):
        """Copy the (local) files at relpaths into a folder of dst the user chooses, each by its name (one there of that
        name left as it is), once they confirm. Returns [] (they're still missing at their own paths), or None"""
        dst_name = self._dst.screen_name()
        header = "Copy %s into which folder of %s?" % (replica_ops.files_text(len(relpaths)), dst_name)
        if replica_ops.is_local(self._dst):
            chosen = picker.pick_under_dir(self._dst.fullpath(), dirs_only=True, lazy=True, header=header)
            folder = None if chosen is None else os.path.relpath(chosen, self._dst.fullpath())
        else:
            chosen = picker.pick_from_tree(self._dst, header=header, dirs_only=True, root_name=dst_name)
            folder = None if not chosen else chosen[0].relpath
        if folder is None:
            return None
        folder = '' if folder in ('.', '') else folder
        where = "%s/%s" % (dst_name, folder) if folder else dst_name
        moves = [(relpath, posixpath.join(folder, posixpath.basename(relpath))) for relpath in relpaths]
        there = [new for _, new in moves if self._dst.has_file(new)]
        moves = [(relpath, new) for relpath, new in moves if not self._dst.has_file(new)]
        if not moves:
            messages.show("Nothing to copy", ["%s has them all there, by their names." % (where,)], dryrun.label())
            return None
        lines = ["Copy %s into %s?" % (replica_ops.files_text(len(moves)), where)] + text.listed(
            ["  %s" % (relpath,) for relpath, _ in moves])
        if there:
            lines.append("%s there by %s name stay%s as %s." % (replica_ops.files_text(len(there)), "its" if len(there) == 1 else "their",
                                                                 "s" if len(there) == 1 else "", "it is" if len(there) == 1 else "they are"))
        if dryrun.DRYRUN:
            lines.append(dryrun.note())
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines), title="Copy",
                              label=self.LABELS[self.COPY_ELSEWHERE]) != self.CONFIRM_YES:
            return None
        # (Each read from its path here, written at its new one there: copy_in() takes the entries' full paths)
        files = [entries.FileEntry(posixpath.basename(new), new, os.path.join(self._src.fullpath(), relpath)) for relpath, new in moves]
        title = "Copying %s into %s" % (replica_ops.files_text(len(files)), where) + (" (a dry run)" if dryrun.DRYRUN else "")
        with messages.progress_screen(title, dryrun.label()):
            self._dst.copy_in(files)
        if not dryrun.DRYRUN:
            self._note(self._dst, 'copied', len([1 for entry in files if self._dst.has_file(entry.relpath)]), self._src.displayname())
        return []

    def _copy_or_remove(self, action, relpaths, to_trash=False):
        """Copy the files at relpaths to dst, or remove them from src (action), once the user confirms.
        Returns the ones done (in a dry run, the ones it would have done), or None if the user didn't
        confirm. With to_trash, a local src's go to the desktop's trash, rather than for good."""
        # (A drive without a trash: for good, and the confirmation says so)
        to_trash = to_trash and replica_ops.is_local(self._src) and self._src.has_trash()
        if not self._confirm(action, relpaths, to_trash):
            return None
        self._last_action = action
        src_name, dst_name = self._src.screen_name(), self._dst.screen_name()
        count = replica_ops.files_text(len(relpaths))
        files = [self._file_entry(relpath) for relpath in relpaths]
        if action == self.COPY:
            title = "Copying %s from %s to %s" % (count, src_name, dst_name)
        else:
            title = "Removing %s from %s" % (count, src_name)
        if dryrun.DRYRUN:
            title += " (a dry run)"
        # Copied over dst's other versions of the ones that differ
        replacing = (self._dst.replacing() if action == self.COPY and any(relpath in self.differs for relpath in relpaths)
                     else contextlib.nullcontext())
        added = _Added()
        self._dst.add_listener(added)
        try:
            with messages.progress_screen(title, dryrun.label()), (self._src.trashing() if to_trash else
                                                                   contextlib.nullcontext()), replacing:
                if action == self.COPY:
                    self._copy(files)
                else:
                    self._remove(files)
        finally:
            self._dst.remove_listener(added)
        if dryrun.DRYRUN:
            return relpaths
        if action == self.COPY:
            # (The ones that differ were there before: the ones copied are the ones made)
            done = [relpath for relpath in relpaths if relpath in added.relpaths or
                    (relpath not in self.differs and self._dst.has_file(relpath))]
            self._note(self._dst, 'copied', len(done), self._src.displayname())
        else:
            done = [relpath for relpath in relpaths if not self._src.has_file(relpath)]
            self._note(self._src, 'removed', len(done))
        return done

    def _confirm(self, action, relpaths, to_trash=False, replica=None):
        """Whether the user confirms copying or removing the files at relpaths (of src, or the replica
        they're in, if it isn't); a removal, twice"""
        replica = replica or self._src
        if action == self.COPY:
            question = "Copy %s from %s to %s?" % (replica_ops.files_text(len(relpaths)), self._src.screen_name(),
                                                   self._dst.screen_name())
        else:
            question = "Remove %s from %s?" % (replica_ops.files_text(len(relpaths)), replica.screen_name())
        changed = [relpath for relpath in relpaths if relpath in self.differs]
        lines = [question] + text.listed(["  %s%s" % (relpath, "  (replaces %s's)" % (self._dst.screen_name(),)
                                                       if action == self.COPY and relpath in self.differs else "")
                                          for relpath in relpaths], self.MAX_FILES_LISTED)
        lines += (self._src.copy_notes(relpaths) if action == self.COPY else
                  replica.removal_notes(relpaths))
        if changed and action == self.COPY:
            lines.append(self._replaced_note(self._dst, len(changed)))
            older = [relpath for relpath in changed if differing.newer(self.differs[relpath]) < 0]
            if older:
                lines.append("Careful: %s older here than in %s, so Copy replaces %s." %
                             (replica_ops.files_text(len(older)) + (" is" if len(older) == 1 else " are"), self._dst.screen_name(),
                              "a newer version" if len(older) == 1 else "newer versions"))
        elif changed and replica is self._src:
            lines.append("%s has other versions of %s of them, which stay." % (self._dst.screen_name(), len(changed)))
        if dryrun.DRYRUN:
            lines.append(dryrun.note())
        if not self._said_yes(lines, self.LABELS[action]):
            return False
        return action != self.REMOVE or self._is_sure(len(relpaths), replica.screen_name(), not replica_ops.is_local(replica),
                                                      to_trash, self.LABELS[action])

    def _copy(self, files):
        # It adds what it copies to dst's tree, so the next diff doesn't list them
        self._dst.copy_in(files, self._src)

    def _remove(self, files):
        self._src.remove_files(files)
