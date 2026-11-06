"""LocalCopying files into a local replica (replacing one, if it's asked to), and within it"""
import os
import shutil

from dirdelta.hashes import hashcache
from dirdelta.trees.localdiskdirtree import fs
from dirdelta.trees.localdiskdirtree.fs import PART_PREFIX
from dirdelta.ui import messages


class LocalCopying(object):
    """Copies (LocalReplica's)"""

    def _copy_file(self, file_entry, source):
        reason = source.cant_fetch(file_entry.relpath) if source is not None else None
        if reason is not None:
            messages.print_line("Skipped %s: %s" % (file_entry.relpath, reason), "yellow")
            return False
        dest_path = os.path.join(self._rootpath, file_entry.relpath)
        if self._is_replacing and os.path.lexists(dest_path):
            return self._replace_file(file_entry, source, dest_path)
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
                    return False
            if source is not None:
                source.fetch_file(file_entry.relpath, dest_path)
            else:
                self._copy_local_file_to_tree_with_path(file_entry.full_filesystem_path(), dest_path)
        except OSError as ex:
            messages.print_line("Copy failed: %s" % (str(ex),), "red")
            self._drop_copy(dest_path, did_dest_exist)
            return False
        except BaseException:
            self._drop_copy(dest_path, did_dest_exist)
            raise
        self._file_added(file_entry.relpath)
        return True

    def _replace_file(self, file_entry, source, dest_path):
        """_copy_file() over the file at dest_path (inside replacing()): copied next to it first, so a
        copy that fails leaves it as it was; then it goes to the desktop's trash, and the copy takes
        its place. Returns whether it was replaced."""
        part_path = os.path.join(os.path.dirname(dest_path), PART_PREFIX + os.path.basename(dest_path))
        try:
            try:
                if source is not None:
                    source.fetch_file(file_entry.relpath, part_path)
                else:
                    self._copy_local_file_to_tree_with_path(file_entry.full_filesystem_path(), part_path)
                fs._trash(dest_path)
                os.rename(part_path, dest_path)
            except BaseException:
                if os.path.lexists(part_path):
                    os.unlink(part_path)
                raise
        except OSError as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        # Its hashes, if they were put, are the copy's
        hashcache.move(part_path, dest_path)
        # What listens drops what it knew of the old one
        self._file_removed(file_entry.relpath)
        self._file_added(file_entry.relpath)
        return True

    def _drop_copy(self, dest_path, did_dest_exist):
        """Undo a copy that failed or was cut off (e.g. by Ctrl-C), if it started: a copy cut off in
        the middle leaves part of the file, dropped unless it's a file that was there before"""
        if not did_dest_exist and os.path.exists(dest_path):
            os.unlink(dest_path)

    def _copy_within(self, relpath, new_relpath, to=None):
        to = to or self
        new_path = os.path.join(to.fullpath(), new_relpath)
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s: %s is there already" % (relpath, new_relpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            self._copy_local_file_to_tree_with_path(os.path.join(self._rootpath, relpath), new_path)
        except OSError as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        to._file_added(new_relpath)
        return True

    def fetch_file(self, relpath, local_path):
        self._copy_local_file_to_tree_with_path(os.path.join(self._rootpath, relpath), local_path)

    def _copy_local_file_to_tree_with_path(self, src, dst):
        # copy2: with its modification time, rather than the copy's
        shutil.copy2(src, dst)
        # The copy's hashes are the file's, if they're known (so it isn't read again to hash it)
        hashes = hashcache.get_all(src)
        if hashes:
            hashcache.put(dst, hashes)
