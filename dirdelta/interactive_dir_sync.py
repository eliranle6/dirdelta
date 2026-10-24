from dirdelta import dirtree
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import picker


class InteractiveDirSync(object):
    """Copying or removing the files in src that aren't in dst, picked by the user."""
    COPY = 'copy'
    REMOVE = 'remove'

    # The confirmation menu's options: No first, so it's the one selected at first
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    # How many of the picked files the confirmation lists
    MAX_FILES_LISTED = 5

    def __init__(self, src, dst):
        self._src = src
        self._dst = dst
        self._selected = dict()

    def view_diff(self, src, dst):
        missing = dst.get_unknown_entries_in_given_dirtree(src)
        header = "Files in %s, which are not in %s:" % (src.fullpath(), dst.fullpath())
        picker.pick_from_tree(missing, header=header)

    def sync(self, action):
        """Let the user pick files of src that aren't in dst, then copy them to dst (action COPY) or
        remove them from src (REMOVE), once the user confirms; repeat with what's left, until the user
        quits. If the user doesn't confirm, they pick again, starting from what they picked."""
        picked = None
        while True:
            missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
            if not missing.does_dir_contain_any_files():
                messages.print_line("Nothing to synchronize; Destination dir alread contains all files "
                                     "in source dir.")
                break
            entries = self._chooseFiles(missing, action, picked)
            if entries is None:
                messages.print_line("Sync ended by user's request.")
                break
            self._selected = self._files(entries)
            if not self._selected:
                break
            if not self._confirm(action):
                picked = entries
                continue
            picked = None
            nr_files = len(self._selected)
            if action == self.COPY:
                title = "Copying %d files from %s to %s" % (nr_files, self._src.fullpath(),
                                                           self._dst.fullpath())
            else:
                title = "Removing %d files from %s" % (nr_files, self._src.fullpath())
            if localdiskdirtree.DRYRUN:
                title += " (a dry run)"
            with messages.progress_screen(title):
                if action == self.COPY:
                    self._copy()
                else:
                    self._remove()

    def _chooseFiles(self, missing, action, picked=None):
        purpose = ("copy to %s" % (self._dst.fullpath(),) if action == self.COPY else
                   "remove from %s" % (self._src.fullpath(),))
        tree_header = ("Files in %s, which are not in %s. Pick the ones to %s:\n"
                       "(To select a file, press Space. When finished, press Enter.)" %
                       (self._src.fullpath(), self._dst.fullpath(), purpose))
        return picker.pick_from_tree(missing, header=tree_header, multi=True, picked=picked)

    @staticmethod
    def _files(entries):
        """The picked entries' files (by full path): picking a dir also picks it, but only its files
        are copied or removed"""
        return {entry.fullpath: entry for entry in entries if isinstance(entry, dirtree.FileEntry)}

    def _confirm(self, action):
        files = list(self._selected.values())
        if action == self.COPY:
            question = "Copy %d files from %s to %s?" % (len(files), self._src.fullpath(),
                                                         self._dst.fullpath())
        else:
            question = "Remove %d files from %s?" % (len(files), self._src.fullpath())
        lines = [question] + ["  %s" % (entry,) for entry in files[:self.MAX_FILES_LISTED]]
        if len(files) > self.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(files) - self.MAX_FILES_LISTED,))
        if localdiskdirtree.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines))
        return answer == self.CONFIRM_YES

    def _copy(self):
        _dirtree = dirtree.factory_from_list_of_file_entries(self._selected.values(),
                                                              self._src.fullpath())
        self._dst.copy_inner_entries_from_dirtree(_dirtree)
        self._dst.update_from_filesystem()

    def _remove(self):
        self._src.remove_files(list(self._selected.values()))
