import os

import treepicker
import cursesswitch
import dirtree
import menu


class InteractiveDirSync(object):
    _OPTION_COPY = "Copy selected files"
    _OPTION_REMOVE = "Remove selected files"
    _OPTION_NOTHING = "Do nothing"
    _OPTION_RESELECT = "Reselect files"

    def __init__(self, src, dst):
        self._src = src
        self._dst = dst
        self._selected = dict()

    def view_diff(self, src, dst):
        missing = dst.get_unknown_entries_in_given_dirtree(src)
        self._chooseFiles(missing)

    def sync(self):
        while True:
            missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
            if not missing.does_dir_contain_any_files():
                cursesswitch.print_string("Nothing to synchronize; Destination dir alread contains all files "
                                     "in source dir.")
                break
            self._selected = self._chooseFiles(missing)
            if self._selected is None:
                cursesswitch.print_string("Sync ended by user's request.")
                break
            if not self._selected:
                break
            cursesswitch.print_string("%d files were chosen to copy so far." % (len(self._selected),))
            option = menu.run_menu([
                (self._OPTION_NOTHING, None),
                (self._OPTION_RESELECT, None),
                (self._OPTION_COPY, self._copy),
                (self._OPTION_REMOVE, self._remove),
            ])
            if option in (None, self._OPTION_NOTHING):
                break

    def _chooseFiles(self, missing):
        tree_header = ("Files in %s, which are not in %s:\n"
                       "(To select a file, press Space. When finished, press Enter.)" %
                       (self._src.fullpath(), self._dst.fullpath()))
        tree_picker = treepicker.TreePicker(missing, header=tree_header)
        entries = tree_picker.pick()
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
        file_entries = self._selected.values()
        for index, file_entry in enumerate(file_entries):
            cursesswitch.print_string("Removing {} ({} out of {})".format(
                file_entry, index + 1, len(file_entries)))
            os.unlink(file_entry.full_filesystem_path())
            # Keep the in-memory source tree in sync so the next diff doesn't list the file again
            self._src.remove_node(file_entry.relpath)

