"""LocalRemoving a local replica's files (and the dirs they leave empty)"""
import os
import shutil

from dirdelta.trees.localdiskdirtree import fs
from dirdelta.trees.localdiskdirtree import whole_dirs
from dirdelta.ui import messages
from dirdelta.util import text
from dirdelta.util import dryrun


# The most whole dirs a confirmation names
MAX_DIRS_SAID = 5


class LocalRemoving(object):
    """Removals (LocalReplica's)"""

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files: the topmost dirs all that's in which is picked (whole_dirs(), on the disk), each as one,
        then the others one by one; and then the dirs that removing them left empty"""
        picked = {file_entry.relpath for file_entry in file_entries}
        in_removed_dirs = set()
        for dirpath in whole_dirs.whole_dirs(self._rootpath, picked, self._is_kept):
            dir_files = [relpath for relpath in picked if relpath.startswith(dirpath + '/')]
            starting("dir %s/ and its %s" % (dirpath, text.files(len(dir_files))), len(dir_files))
            if dryrun.DRYRUN or self._remove_dir(dirpath, dir_files):
                removed(len(dir_files))
                in_removed_dirs.update(dir_files)
        others = [file_entry for file_entry in file_entries if file_entry.relpath not in in_removed_dirs]
        super()._remove_files(others, starting, removed)
        if not dryrun.DRYRUN:
            self._remove_emptied_dirs(others)

    def _remove_dir(self, dirpath, files):
        """Remove the dir at dirpath, with its files (relpaths, all that's in it), as one. Returns whether it was."""
        try:
            if self._is_trashing:
                fs.trash(os.path.join(self._rootpath, dirpath))
            else:
                shutil.rmtree(os.path.join(self._rootpath, dirpath))
        except OSError as error:
            # Said; its files are then removed one by one
            messages.print_line("Removing %s/ as one failed (%s): its files one by one" % (dirpath, error), "red")
            return False
        for relpath in files:
            self._file_removed(relpath)
        self._dir_removed(dirpath)
        return True

    def _remove_emptied_dirs(self, file_entries):
        """Remove the dirs of the (removed) files that are empty, and the dirs they're in that this
        leaves empty, up to (not including) the root. Only empty ones: rmdir fails on one with
        anything in it, which is then kept, as are the dirs it's in."""
        nr_removed = 0
        dirpaths = {os.path.dirname(file_entry.full_filesystem_path()) for file_entry in file_entries}
        # The deepest first, so a dir's emptied subdirs are gone when it's tried
        for dirpath in sorted(dirpaths, key=lambda dirpath: dirpath.count(os.sep), reverse=True):
            while (dirpath.startswith(self._rootpath.rstrip(os.sep) + os.sep) and
                   os.path.relpath(dirpath, self._rootpath) not in self._kept_dirs):
                try:
                    os.rmdir(dirpath)
                except OSError:
                    break
                nr_removed += 1
                self._dir_removed(os.path.relpath(dirpath, self._rootpath))
                dirpath = os.path.dirname(dirpath)
        if nr_removed:
            messages.print_line("Removed %d dirs left empty" % (nr_removed,))

    def removal_notes(self, relpaths):
        dirs = whole_dirs.whole_dirs(self._rootpath, relpaths, self._is_kept)
        lines = ["Dirs left empty are removed too."]
        if dirs:
            lines.append("%d dirs all of whose files are checked (nothing else is in them) go as one each: %s" % (
                len(dirs), ', '.join(dirpath + '/' for dirpath in dirs[:MAX_DIRS_SAID]) + (', ...' if len(dirs) > MAX_DIRS_SAID else '')))
        return lines

    def _remove_file(self, file_entry):
        try:
            if self._is_trashing:
                fs.trash(file_entry.full_filesystem_path())
            else:
                os.unlink(file_entry.full_filesystem_path())
        except OSError as error:
            # Said, and the others go on (it's kept, in the tree too)
            messages.print_line("Remove failed: %s" % (error,), "red")
            return False
        self._file_removed(file_entry.relpath)
        return True
