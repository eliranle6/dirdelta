from dirdelta import dirtree
from dirdelta import messages
from dirdelta import picker


class InteractiveDirSync(object):
    """Copying or removing the files in src that aren't in dst, picked by the user."""
    COPY = 'copy'
    REMOVE = 'remove'

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
        remove them from src (REMOVE); repeat with what's left, until the user quits."""
        while True:
            missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
            if not missing.does_dir_contain_any_files():
                messages.print_line("Nothing to synchronize; Destination dir alread contains all files "
                                     "in source dir.")
                break
            self._selected = self._chooseFiles(missing, action)
            if self._selected is None:
                messages.print_line("Sync ended by user's request.")
                break
            if not self._selected:
                break
            if action == self.COPY:
                self._copy()
            else:
                self._remove()

    def _chooseFiles(self, missing, action):
        purpose = ("copy to %s" % (self._dst.fullpath(),) if action == self.COPY else
                   "remove from %s" % (self._src.fullpath(),))
        tree_header = ("Files in %s, which are not in %s. Pick the ones to %s:\n"
                       "(To select a file, press Space. When finished, press Enter.)" %
                       (self._src.fullpath(), self._dst.fullpath(), purpose))
        entries = picker.pick_from_tree(missing, header=tree_header, multi=True)
        if entries is None:
            return None
        files = [entry for entry in entries if isinstance(entry, dirtree.FileEntry)]
        selected = dict()
        for file_entry in files:
            selected[file_entry.fullpath] = file_entry
        return selected

    def _copy(self):
        _dirtree = dirtree.factory_from_list_of_file_entries(self._selected.values(),
                                                              self._src.fullpath())
        self._dst.copy_inner_entries_from_dirtree(_dirtree)
        self._dst.update_from_filesystem()

    def _remove(self):
        self._src.remove_files(list(self._selected.values()))
