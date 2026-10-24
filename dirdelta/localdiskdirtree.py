import os
import shutil

from dirdelta import dirtree
from dirdelta import findcmdwrapper
from dirdelta import messages

# Unless DRYRUN=0, actions that change files (copying, removing) only say what they would do. The
# tree is updated as if they did it, though.
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
        # find's messages about what it couldn't read in the last scan, so the tree may lack
        self.scan_errors = []

    def update_from_filesystem(self, max_depth=None, file_extentions=None, dirs_only=False,
                               include_hidden=True):
        if not self._silent:
            messages.print_line("Scanning directory %s..." % (self._rootpath,))
        errors = []
        if not dirs_only:
            # Read disk for files
            full_paths = findcmdwrapper.find_files(
                self._rootpath, max_depth, file_extentions, include_hidden, errors)

            # Create nodes
            for filepath in full_paths:
                self.add_file_by_fullpath(filepath)

        # Add directories
        dirnames_fullpath = findcmdwrapper.find_dirs(self._rootpath, max_depth, include_hidden, errors)
        # Both finds hit the same unreadable paths
        self.scan_errors = list(dict.fromkeys(errors))
        dirnames_fullpath.remove(self.fullpath())
        for dirpath in dirnames_fullpath:
            self.create_dir_node_from_fullpath_if_not_exists(dirpath)

    def copy_inner_entries_from_dirtree(self, dirtree):
        files = list(dirtree.iter_files())
        # In a dry run nothing is written (dirs included), but the tree is updated as if it was
        verb = "Dry run, not copying" if DRYRUN else "Copying"
        nr_copied = 0
        try:
            for index, file_entry in enumerate(files):
                messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, index + 1, len(files)))
                if self._copy_file(file_entry):
                    nr_copied += 1
        except KeyboardInterrupt:
            messages.note_stopped()
        if DRYRUN:
            messages.print_line("Dry run: nothing was copied to %s (DRYRUN=0 copies)" % (self._rootpath,))
        else:
            messages.print_line("Copied %d of %d files to %s" % (nr_copied, len(files), self._rootpath))

    def _copy_file(self, file_entry):
        """Copy file_entry (of another tree) into this tree, at the same relative path. Returns whether
        it was copied (or, in a dry run, would have been)."""
        new_file_entry = self.add_file_by_relpath(file_entry.relpath)
        dest_path = new_file_entry.full_filesystem_path()
        did_dest_exist = os.path.exists(dest_path)
        try:
            dest_dirpath = os.path.dirname(dest_path)
            if os.path.exists(dest_dirpath):
                assert os.path.isdir(dest_dirpath)
            elif not DRYRUN:
                try:
                    os.makedirs(dest_dirpath)
                except OSError as ex:
                    messages.print_line("Copy failed: %s" % (str(ex),), "red")
                    self.remove_node(new_file_entry.relpath)
                    return False
            self._copy_local_file_to_tree_with_path(file_entry.full_filesystem_path(), dest_path)
            return True
        except BaseException:
            self.remove_node(new_file_entry.relpath)
            # A copy cut off in the middle (e.g. Ctrl-C) leaves part of the file: drop it, unless
            # it's a file that was there before
            if not DRYRUN and not did_dest_exist and os.path.exists(dest_path):
                os.unlink(dest_path)
            raise

    def remove_files(self, file_entries):
        """Delete the files, and drop them from the tree (so the next diff doesn't list them)."""
        verb = "Dry run, not removing" if DRYRUN else "Removing"
        nr_removed = 0
        try:
            for index, file_entry in enumerate(file_entries):
                messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, index + 1, len(file_entries)))
                if not DRYRUN:
                    os.unlink(file_entry.full_filesystem_path())
                self.remove_node(file_entry.relpath)
                nr_removed += 1
        except KeyboardInterrupt:
            messages.note_stopped()
        if DRYRUN:
            messages.print_line("Dry run: nothing was removed from %s (DRYRUN=0 removes)" % (self._rootpath,))
        else:
            messages.print_line("Removed %d of %d files from %s" % (nr_removed, len(file_entries),
                                                                   self._rootpath))

    def _copy_local_file_to_tree_with_path(self, src, dst):
        if DRYRUN:
            return
        shutil.copy(src, dst)
