"""LocalMoving a local replica's files and dirs"""
import os

from dirdelta.hashes import hashcache
from dirdelta.trees import entries
from dirdelta.trees.localdiskdirtree.fs import rename
from dirdelta.ui import messages


class LocalMoving(object):
    """Moves (LocalReplica's)"""

    def files_under(self, dirpath):
        # A symlink to a dir is one too, so a dir with one isn't moved whole (it isn't one of the moves).
        path = os.path.join(self._rootpath, dirpath)
        if not dirpath or os.path.islink(path) or not os.path.isdir(path):
            return []
        found = []
        for walked, dirnames, filenames in os.walk(path):
            relative = os.path.relpath(walked, self._rootpath)
            found += [os.path.join(relative, name) for name in filenames]
            found += [os.path.join(relative, name) for name in dirnames
                      if os.path.islink(os.path.join(walked, name))]
        return found

    def exists(self, relpath):
        return os.path.lexists(os.path.join(self._rootpath, relpath))

    def cant_change(self, relpath):
        if not os.access(os.path.dirname(os.path.join(self._rootpath, relpath)), os.W_OK):
            return "it's on a read-only dir"
        return None

    def _is_stuck(self, relpath):
        """Whether what's at relpath can't leave its dir (cant_change(); said): between filesystems, a
        move is a copy then a removal, which would fail only after the copy was made"""
        if self.cant_change(relpath) is None:
            return False
        messages.print_line("Skipped %s: it's on a read-only dir, so it can only be copied" % (relpath,), "yellow")
        return True

    def _move_dir(self, dirpath, new_dirpath, to=None):
        to = to or self
        path = os.path.join(self._rootpath, dirpath)
        new_path = os.path.join(to.fullpath(), new_dirpath)
        if self._is_stuck(dirpath):
            return False
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s/: %s is there already" % (dirpath, new_dirpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            rename(path, new_path)
        except OSError as error:
            messages.print_line("Move failed: %s" % (error,), "red")
            return False
        # Its files' hashes, under their new paths (between filesystems, a copy may have other times,
        # and then they're hashed again)
        hashcache.move(path, new_path)
        self._dir_moved(dirpath, new_dirpath, to)
        # The dirs it was in, if it leaves them empty, as a removal does
        self._remove_emptied_dirs([entries.FileEntry(os.path.basename(dirpath), dirpath, path)])
        return True

    def _move_file(self, relpath, new_relpath, to=None):
        to = to or self
        path = os.path.join(self._rootpath, relpath)
        new_path = os.path.join(to.fullpath(), new_relpath)
        if self._is_stuck(relpath):
            return False
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s: %s is there already" % (relpath, new_relpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            rename(path, new_path)
        except OSError as error:
            messages.print_line("Move failed: %s" % (error,), "red")
            return False
        hashcache.move(path, new_path)
        if to is self:
            self._file_moved(relpath, new_relpath)
        else:
            self._file_removed(relpath)
            to._file_added(new_relpath)
        # As a removal does
        self._remove_emptied_dirs([entries.FileEntry(os.path.basename(relpath), relpath, path)])
        return True
