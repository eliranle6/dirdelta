import os

import treepicker
import cursesswitch
from fspick import dirtree
from treepicker import optionpicker


class InteractiveDirSync(object):
    _OPTION_COPY = "Copy selected files"
    _OPTION_REMOVE = "Remove selected files"
    _OPTION_NOTHING = "Do nothing"
    _OPTION_RESELECT = "Reselect files"

    def __init__(self, src, dst):
        self._src = dirtree.DirTree.factory_from_filesystem(src,
                                                            file_extentions=dirtree.MUSIC_FILE_EXTENTIONS)
        self._dst = dirtree.DirTree.factory_from_filesystem(dst,
                                                            file_extentions=dirtree.MUSIC_FILE_EXTENTIONS)
        self._selected = dict()

    def sync(self):
        missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
        while True:
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
            option = self._chooseWhatToDoWithFiles()
            if option == self._OPTION_NOTHING:
                break
            elif option == self._OPTION_COPY:
                self._copy()
                self._update_from_filesystem()
                missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
                self._selected = dict()
            elif option == self._OPTION_REMOVE:
                self._remove()
            elif option == self._OPTION_RESELECT:
                pass
            else:
                assert False, option

    def _chooseFiles(self, missing):
        tree_header = ("Files in %s, which are not in %s:\n"
                       "(To select a file, press Space. When finished, press Enter.)" %
                       (self._src, self._dst))
        tree_picker = treepicker.TreePicker(missing, header=tree_header)
        entries = tree_picker.pick()
        if entries is None:
            return None
        files = [entry for entry in entries if isinstance(entry, dirtree.FileEntry)]
        selected = dict()
        for file_entry in files:
            selected[file_entry.fullpath()] = file_entry
        return selected

    def _chooseWhatToDoWithFiles(self):
        options = [self._OPTION_NOTHING, self._OPTION_RESELECT]
        if self._selected:
            options.extend([self._OPTION_COPY, self._OPTION_REMOVE])
        picker = optionpicker.OptionPickerByMenuTraverse(options)
        return picker.pick_one()

    def _update_from_filesystem(self):
        self._dst.update_from_filesystem()

    def _copy(self):
        _dirtree = dirtree.DirTree.factory_from_list_of_file_entries(self._selected.values(),
                                                                     self._src.fullpath())
        self._dst.copy_inner_entries_from_dirtree(_dirtree)

    def _remove(self):
        file_entries = self._selected.values()
        for index, file_entry in enumerate(file_entries):
            cursesswitch.print_string("Removing %s (%d out of %d)" % (file_entry, index + 1, len(file_entries)))
            os.unlink(file_entry.full_filesystem_path())


if __name__ == "__main__":
    sync = InteractiveDirSync('alpha', 'bravo')
    sync.sync()
