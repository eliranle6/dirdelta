"""LocalRemoving a local replica's files (and the dirs they leave empty)"""
import os

from dirdelta.trees.localdiskdirtree import fs
from dirdelta.ui import messages
from dirdelta.util import dryrun


class LocalRemoving(object):
    """Removals (LocalReplica's)"""

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files, and then the dirs that removing them left empty"""
        super()._remove_files(file_entries, starting, removed)
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
        return ["Dirs left empty are removed too."]

    def _remove_file(self, file_entry):
        try:
            if self._is_trashing:
                fs._trash(file_entry.full_filesystem_path())
            else:
                os.unlink(file_entry.full_filesystem_path())
        except OSError as error:
            # Said, and the others go on (it's kept, in the tree too)
            messages.print_line("Remove failed: %s" % (error,), "red")
            return False
        self._file_removed(file_entry.relpath)
        return True
