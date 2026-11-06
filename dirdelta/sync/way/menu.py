"""The action menu of the picked files"""
import os

from dirdelta.drive import clouddirtree
from dirdelta.matching import elsewhere
from dirdelta.sync import replica_ops
from dirdelta.ui import filescreen
from dirdelta.ui import messages
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.util import archives


class Menu(object):
    """The action menu (InteractiveDirSync's)"""

    def _act(self, relpaths, selected=None):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (in a dry run, the ones it would have done), or None if the
        user chose nothing (or didn't confirm, or opened them); or filescreen.READ_ANEW to read the folder of
        selected (the picker's selection, a file or a dir; by default the first file) anew from
        Drive, as the key does."""
        if selected is None:
            selected = relpaths[0]
        clouds = [replica for replica in (self._src, self._dst) if isinstance(replica, clouddirtree.CloudDirTree)]
        folder = os.path.dirname(selected) if self._src.has_file(selected) else selected
        # The ones that differ (dst has another version of each), and the others, which dst lacks
        changed = [relpath for relpath in relpaths if relpath in self.differs]
        only_here = [relpath for relpath in relpaths if relpath not in self.differs]
        may_be_there = []
        if only_here:
            if not self.dst_index.is_built():
                messages.print_line("Looking for files of the same names in %s..." % (self._dst.displayname(),))
            # The ones that may be in dst, moved or renamed: their contents are compared before a Rename
            may_be_there = elsewhere.may_be_elsewhere(only_here, self._src, self.dst_index, self.checked,
                                                      self.src_index)
        nr_renamed_in_src = sum(1 for relpath in may_be_there if self._src.cant_move(relpath) is None)
        src_name, dst_name = self._src.displayname(), self._dst.displayname()
        count = replica_ops._files(len(relpaths))
        options = {
            self.COPY: (self._copy_label(relpaths, changed, self._src, self._dst),
                        self._cant_copy(self._src, self._dst)),
            self.REMOVE: ("Remove the %s from %s" % (count, src_name),
                          None if replica_ops.is_writable(self._src) else "can't: it's read-only"),
            # Each counts the picked files that may be in dst, moved or renamed. The replica last,
            # as in the others, so a long path doesn't hide what it does.
            self.RENAME_IN_DST: ("Rename the files matching %s of these to these paths, in %s" %
                                 (len(may_be_there), dst_name),
                                 self._cant_rename(self._dst, len(may_be_there))),
            self.RENAME_IN_SRC: ("Rename %s of these to their matches' paths, in %s" %
                                 (replica_ops._files(nr_renamed_in_src), src_name),
                                 self._cant_rename(self._src, nr_renamed_in_src)),
        }
        if changed:
            options[self.COPY_BACK] = (("Replace it with its version in %s" if len(relpaths) == 1 else
                                        "Replace these with their versions in %s" if not only_here else
                                        "Replace the %d of these that differ with their versions in %%s" % (len(changed),)) %
                                       (dst_name,), self._cant_copy(self._dst, self._src))
        options[self.ASK_AI] = ("Ask AI what to do with %s, and review its plan" %
                                ("it" if len(relpaths) == 1 else "the " + count,),
                                None if only_here else "can't: it's for the files %s lacks" % (dst_name,))
        if len(relpaths) == 1 and archives.is_archive(relpaths[0]):
            options[self.EXPLORE] = ("Explore it: what's in the zip", None)
        options[self.OPEN] = ("Open %s with %s program%s" %
                              ("it" if len(relpaths) == 1 else "the " + count,
                               "its" if len(relpaths) == 1 else "their", "" if len(relpaths) == 1 else "s"),
                              None if len(relpaths) <= opening.MAX_OPENED else
                              "can't: more than %d at once" % (opening.MAX_OPENED,))
        if clouds:
            options[self.READ_ANEW] = ("Read %s anew from Google Drive" %
                                       (' and '.join(os.path.join(replica.displayname(), folder).rstrip('/') + '/'
                                                     for replica in clouds),), None)
        # After its key, if a picker's key does it too
        prefixes = picker.shortcut_prefixes([self.NOTHING] + [label for label, _ in options.values()],
                                            {label: self.SHORTCUTS[action] for action, (label, _) in options.items()
                                             if action in self.SHORTCUTS})
        def option(action):
            label, reason = options[action]
            return picker.Option(action, label, prefixes[label] + label if reason is None else
                                 picker.Disabled(picker.unstyled(prefixes[label]) + "%s: %s" % (label, reason)))
        # Similar actions together, a blank line between each kind
        kinds = [[self.ASK_AI], [self.COPY, self.COPY_BACK], [self.REMOVE], [self.RENAME_IN_DST, self.RENAME_IN_SRC],
                 [self.EXPLORE, self.OPEN, self.READ_ANEW]]
        choices = picker.grouped([[picker.Option(self.NOTHING, self.NOTHING, prefixes[self.NOTHING] + self.NOTHING)]] +
                                 [[option(action) for action in kind if action in options] for kind in kinds])
        if not changed:
            header = "%s picked in %s, which %s lacks. What to do with them?" % (count, src_name, dst_name)
        elif not only_here:
            header = "%s picked in %s, which %s has other versions of. What to do with them?" % (count, src_name, dst_name)
        else:
            header = ("%s picked in %s: %d %s lacks, %d it has other versions of. What to do with them?" %
                      (count, src_name, len(only_here), dst_name, len(changed)))
        action = picker.pick_option(choices, header=header, title="What to do")
        if action not in options:
            return None
        if action == self.OPEN:
            if opening.confirm(self._opener, relpaths, relpaths):
                self._opener.open_in_background(relpaths, relpaths)
            return None
        if action == self.READ_ANEW:
            return filescreen.READ_ANEW
        if action in (self.RENAME_IN_DST, self.RENAME_IN_SRC):
            moves = self._renames(action, may_be_there)
            return None if moves is None else self._rename(action, moves)
        if action == self.ASK_AI:
            return self._ask_ai(relpaths, relpaths)
        if action == self.EXPLORE:
            self._explore(relpaths[0], set(relpaths))
            return None
        if action == self.COPY_BACK:
            return self._copy_back(changed)
        return self._copy_or_remove(action, relpaths)

    def _copy_label(self, relpaths, changed, src, dst):
        """The action menu's Copy (src to dst): of the files at relpaths, changed are the ones dst has
        other versions of, which it replaces"""
        count = replica_ops._files(len(relpaths))
        if not changed:
            return "Copy the %s to %s" % (count, dst.displayname())
        if len(changed) == len(relpaths):
            return "Copy these versions of the %s to %s, replacing its" % (count, dst.displayname())
        return "Copy the %s to %s, replacing its other versions of %d" % (count, dst.displayname(), len(changed))

    def _cant_copy(self, src, dst):
        """Why src's files can't be copied into dst, or None if they can"""
        if replica_ops.can_copy(src, dst):
            return None
        return "can't: %s" % ("it's read-only" if not replica_ops.is_writable(dst) else "both are Google Drive's",)
