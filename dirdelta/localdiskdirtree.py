import os
import shutil
import subprocess

from dirdelta import dirtree
from dirdelta import dryrun
from dirdelta import messages


def factory(filesystem_dirpath, max_depth=None, silent=False):
    dirtree = LocalDiskDirTree(filesystem_dirpath, silent)
    dirtree.update_from_filesystem(max_depth)
    return dirtree


class LocalDiskDirTree(dirtree.DirTree):
    def __init__(self, filesystem_dirpath, silent):
        filesystem_dirpath = os.path.realpath(filesystem_dirpath)
        super(LocalDiskDirTree, self).__init__(rootpath=filesystem_dirpath, silent=silent)
        # find's messages about what it couldn't read in the last scan, so the tree may lack
        self.scan_errors = []

    def update_from_filesystem(self, max_depth=None):
        """Add the dirs and files on disk (hidden ones too), down to max_depth levels below the root."""
        if not self._silent:
            messages.print_line("Scanning directory %s..." % (self._rootpath,))
        # One find for both files and dirs, each entry its type letter and path, ending with '\0'
        # (paths may hold newlines). Other types (e.g. symlinks) are skipped.
        command = ["find", self._rootpath, "-mindepth", "1"]
        if max_depth is not None:
            command += ["-maxdepth", str(max_depth)]
        command += ["-printf", "%y %p\\0"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.scan_errors = result.stderr.decode('utf-8', 'surrogateescape').splitlines()
        for entry in result.stdout.split(b'\0'):
            # Names needn't be valid UTF-8: decoded like Python decodes paths
            kind, path = entry[:1], os.fsdecode(entry[2:])
            if kind == b'f':
                self.add_file_by_fullpath(path)
            elif kind == b'd':
                self.create_dir_node_from_fullpath_if_not_exists(path)

    def copy_inner_entries_from_dirtree(self, dirtree):
        files = list(dirtree.iter_files())
        # In a dry run nothing changes: no files or dirs, and not the tree
        verb = "Dry run, not copying" if dryrun.DRYRUN else "Copying"
        nr_copied = 0
        is_stopped = False
        try:
            for index, file_entry in enumerate(files):
                messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, index + 1, len(files)))
                if self._copy_file(file_entry):
                    nr_copied += 1
        except KeyboardInterrupt:
            messages.note_stopped()
            is_stopped = True
        ended = "stopped" if is_stopped else "complete"
        if dryrun.DRYRUN:
            messages.print_line("Dry run %s: nothing was copied to %s (DRYRUN=0 copies)" % (ended, self._rootpath))
        else:
            messages.print_line("Copy %s: copied %d of %d files to %s" % (ended, nr_copied, len(files),
                                                                        self._rootpath))

    def _copy_file(self, file_entry):
        """Copy file_entry (of another tree) into this tree, at the same relative path. Returns whether
        it was copied (or, in a dry run, would have been)."""
        if dryrun.DRYRUN:
            return True
        new_file_entry = self.add_file_by_relpath(file_entry.relpath)
        dest_path = new_file_entry.full_filesystem_path()
        did_dest_exist = os.path.exists(dest_path)
        try:
            dest_dirpath = os.path.dirname(dest_path)
            if os.path.exists(dest_dirpath):
                assert os.path.isdir(dest_dirpath)
            else:
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
            if not did_dest_exist and os.path.exists(dest_path):
                os.unlink(dest_path)
            raise

    def remove_files(self, file_entries):
        """Delete the files, and drop them from the tree (so the next diff doesn't list them). A dry run
        changes neither."""
        verb = "Dry run, not removing" if dryrun.DRYRUN else "Removing"
        nr_removed = 0
        is_stopped = False
        try:
            for index, file_entry in enumerate(file_entries):
                messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, index + 1, len(file_entries)))
                if not dryrun.DRYRUN:
                    os.unlink(file_entry.full_filesystem_path())
                    self.remove_node(file_entry.relpath)
                nr_removed += 1
        except KeyboardInterrupt:
            messages.note_stopped()
            is_stopped = True
        ended = "stopped" if is_stopped else "complete"
        if dryrun.DRYRUN:
            messages.print_line("Dry run %s: nothing was removed from %s (DRYRUN=0 removes)" % (ended,
                                                                                          self._rootpath))
        else:
            messages.print_line("Remove %s: removed %d of %d files from %s" % (ended, nr_removed,
                                                                             len(file_entries), self._rootpath))

    def _copy_local_file_to_tree_with_path(self, src, dst):
        shutil.copy(src, dst)
