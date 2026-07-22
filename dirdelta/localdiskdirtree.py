import os
import shutil

import cursesswitch
import dirtree
import findcmdwrapper

DRYRUN = os.environ.get("DRYRUN") != "0"


def factory(filesystem_dirpath, max_depth=None, file_extentions=None, dirs_only=False,
            include_hidden=True, silent=False):
    filesystem_dirpath = os.path.realpath(filesystem_dirpath)
    dirtree = LocalDiskDirTree(filesystem_dirpath, silent)
    dirtree.update_from_filesystem(max_depth, file_extentions, dirs_only, include_hidden)
    dirtree.children(dirtree._root.identifier)
    return dirtree


class LocalDiskDirTree(dirtree.DirTree):
    def __init__(self, filesystem_dirpath, silent):
        filesystem_dirpath = os.path.realpath(filesystem_dirpath)
        super(LocalDiskDirTree, self).__init__(rootpath=filesystem_dirpath, silent=silent)

    def update_from_filesystem(self, max_depth=None, file_extentions=None, dirs_only=False,
                               include_hidden=True):
        if not self._silent:
            cursesswitch.print_string("Scanning directory %s..." % (self._rootpath,))
        if not dirs_only:
            # Read disk for files
            full_paths = findcmdwrapper.find_files(
                self._rootpath, max_depth, file_extentions, include_hidden)

            # Create nodes
            for filepath in full_paths:
                self.add_file_by_fullpath(filepath)

        # Add directories
        dirnames_fullpath = findcmdwrapper.find_dirs(self._rootpath, max_depth, include_hidden)
        dirnames_fullpath.remove(self.fullpath())
        for dirpath in dirnames_fullpath:
            self.create_dir_node_from_fullpath_if_not_exists(dirpath)

    def copy_inner_entries_from_dirtree(self, dirtree):
        files = list(dirtree.iter_files())
        for index, file_entry in enumerate(files):
            cursesswitch.print_string("Copying %s (%d out of %d)" % (file_entry, index + 1, len(files)))
            new_file_entry = self.add_file_by_relpath(file_entry.relpath)
            try:
                dest_dirpath = os.path.dirname(new_file_entry.full_filesystem_path())
                if os.path.exists(dest_dirpath):
                    assert os.path.isdir(dest_dirpath)
                else:
                    try:
                        os.makedirs(dest_dirpath)
                    except OSError as ex:
                        cursesswitch.print_string("Copy failed: %s" % (str(ex),), "red")
                        continue
                self._copy_local_file_to_tree_with_path(
                    file_entry.full_filesystem_path(),
                    new_file_entry.full_filesystem_path())
            except:
                self.remove_node(new_file_entry.relpath)
                raise

    def _copy_local_file_to_tree_with_path(self, src, dst):
        if DRYRUN:
            return
        shutil.copy(src, dst)
