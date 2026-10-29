import collections
import os
import shutil
import subprocess

from dirdelta import dirtree
from dirdelta import dryrun
from dirdelta import messages


# How many of find's error messages a scan warning lists
MAX_SCAN_ERRORS_SHOWN = 3


def factory(filesystem_dirpath, max_depth=None, silent=False):
    dirtree = LocalDiskDirTree(filesystem_dirpath, silent, max_depth)
    dirtree.update_from_filesystem()
    return dirtree


def scan_warning(where, errors):
    """A warning's lines if scanning where (a dir, or a description of dirs) couldn't read everything,
    given find's error messages, since then a diff may list files as missing that are there, or
    miss some; no lines if there are no errors."""
    if not errors:
        return []
    lines = ["find couldn't read everything in %s (%d errors), so the diff may be wrong:" %
             (where, len(errors))]
    lines += ["  " + error for error in errors[:MAX_SCAN_ERRORS_SHOWN]]
    if len(errors) > MAX_SCAN_ERRORS_SHOWN:
        lines.append("  (and %d more)" % (len(errors) - MAX_SCAN_ERRORS_SHOWN,))
    return lines


class LocalDiskDirTree(dirtree.DirTree):
    def __init__(self, filesystem_dirpath, silent, max_depth=None):
        """A tree of the dir, which is empty until update_from_filesystem(), which scans down to
        max_depth levels below it."""
        filesystem_dirpath = os.path.realpath(filesystem_dirpath)
        super(LocalDiskDirTree, self).__init__(rootpath=filesystem_dirpath, silent=silent)
        self.max_depth = max_depth
        # find's messages about what it couldn't read in the last scan, so the tree may lack
        self.scan_errors = []

    def update_from_filesystem(self):
        """Add the dirs and files on disk (hidden ones too), down to max_depth levels below the root."""
        if not self._silent:
            messages.print_line("Scanning directory %s..." % (self._rootpath,))
        # One find for both files and dirs, each entry its type letter and path, ending with '\0'
        # (paths may hold newlines). Other types (e.g. symlinks) are skipped.
        command = ["find", self._rootpath, "-mindepth", "1"]
        if self.max_depth is not None:
            command += ["-maxdepth", str(self.max_depth)]
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

    def file_size(self, relpath):
        try:
            return os.lstat(os.path.join(self._rootpath, relpath)).st_size
        except OSError:
            return None

    def files_by_name(self):
        """As DirTree's, but from a find of the dir (down to max_depth levels), with its files'
        sizes: the tree may not be scanned (see dirdiff.py), or be from an older scan"""
        command = ["find", self._rootpath, "-mindepth", "1"]
        if self.max_depth is not None:
            command += ["-maxdepth", str(self.max_depth)]
        command += ["-type", "f", "-printf", "%s %P\\0"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        found = collections.defaultdict(list)
        for entry in result.stdout.split(b'\0')[:-1]:
            size, relpath = entry.split(b' ', 1)
            relpath = os.fsdecode(relpath)
            found[os.path.basename(relpath)].append((relpath, int(size)))
        return found

    def _copy_file(self, file_entry, source):
        reason = source.cant_fetch(file_entry.relpath) if source is not None else None
        if reason is not None:
            messages.print_line("Skipped %s: %s" % (file_entry.relpath, reason), "yellow")
            return False
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
            if source is not None:
                source.fetch_file(file_entry.relpath, dest_path)
            else:
                self._copy_local_file_to_tree_with_path(file_entry.full_filesystem_path(), dest_path)
            return True
        except OSError as ex:
            messages.print_line("Copy failed: %s" % (str(ex),), "red")
            self._drop_copy(new_file_entry, dest_path, did_dest_exist)
            return False
        except BaseException:
            self._drop_copy(new_file_entry, dest_path, did_dest_exist)
            raise

    def _drop_copy(self, new_file_entry, dest_path, did_dest_exist):
        """Undo a copy that failed or was cut off (e.g. by Ctrl-C), if it started"""
        if new_file_entry.relpath in self:
            self.remove_node(new_file_entry.relpath)
        # A copy cut off in the middle leaves part of the file: drop it, unless it's a file that
        # was there before
        if not did_dest_exist and os.path.exists(dest_path):
            os.unlink(dest_path)

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files, and then the dirs that removing them left empty"""
        super(LocalDiskDirTree, self)._remove_files(file_entries, starting, removed)
        if not dryrun.DRYRUN:
            self._remove_emptied_dirs(file_entries)

    def _remove_emptied_dirs(self, file_entries):
        """Remove the dirs of the (removed) files that are empty, and the dirs they're in that this
        leaves empty, up to (not including) the root. Only empty ones: rmdir fails on one with
        anything in it, which is then kept, as are the dirs it's in."""
        nr_removed = 0
        dirpaths = {os.path.dirname(file_entry.full_filesystem_path()) for file_entry in file_entries}
        # The deepest first, so a dir's emptied subdirs are gone when it's tried
        for dirpath in sorted(dirpaths, key=lambda dirpath: dirpath.count(os.sep), reverse=True):
            while dirpath.startswith(self._rootpath.rstrip(os.sep) + os.sep):
                try:
                    os.rmdir(dirpath)
                except OSError:
                    break
                nr_removed += 1
                relpath = os.path.relpath(dirpath, self._rootpath)
                if relpath in self:
                    self.remove_node(relpath)
                dirpath = os.path.dirname(dirpath)
        if nr_removed:
            messages.print_line("Removed %d dirs left empty" % (nr_removed,))

    def removal_notes(self, relpaths):
        return ["Dirs left empty are removed too."]

    def _remove_file(self, file_entry):
        os.unlink(file_entry.full_filesystem_path())
        # The tree may not have it, if it wasn't scanned (see dirdiff.py)
        if file_entry.relpath in self:
            self.remove_node(file_entry.relpath)
        return True

    def fetch_file(self, relpath, local_path):
        self._copy_local_file_to_tree_with_path(os.path.join(self._rootpath, relpath), local_path)

    def _copy_local_file_to_tree_with_path(self, src, dst):
        shutil.copy(src, dst)
