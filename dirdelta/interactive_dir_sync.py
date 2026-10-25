import os

from dirdelta import dirdiff
from dirdelta import dirtree
from dirdelta import entries
from dirdelta import dryrun
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import picker


class InteractiveDirSync(object):
    """Copying or removing the files in src that aren't in dst, picked by the user."""
    COPY = 'copy'
    REMOVE = 'remove'

    # The confirmation menu's options: No first, so it's the one selected at first
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    # How many of the picked files the confirmation lists
    MAX_FILES_LISTED = 5

    def __init__(self, src, dst):
        self._src = src
        self._dst = dst

    def view_diff(self):
        """Show the files in src that aren't in dst"""
        missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
        header = "Files in %s, which are not in %s:" % (self._src.fullpath(), self._dst.fullpath())
        picker.pick_from_tree(missing, header=header)

    def sync(self, action):
        """Let the user pick files of src that aren't in dst, then copy them to dst (action COPY) or
        remove them from src (REMOVE), once the user confirms. If the user doesn't confirm, they pick
        again, starting from what they picked."""
        missing = self._missing()
        if not missing:
            messages.show("Nothing to %s" % (action,),
                          ["%s has all of %s's files." % (self._dst.fullpath(), self._src.fullpath())],
                          dryrun.label())
            return
        picked = None
        while True:
            picked = self._chooseFiles(missing, action, picked)
            if not picked:
                return
            if self._confirm(action, picked):
                break

        files = [self._file_entry(relpath) for relpath in picked]
        if action == self.COPY:
            title = "Copying %d files from %s to %s" % (len(files), self._src.fullpath(),
                                                       self._dst.fullpath())
        else:
            title = "Removing %d files from %s" % (len(files), self._src.fullpath())
        if dryrun.DRYRUN:
            title += " (a dry run)"
        with messages.progress_screen(title, dryrun.label()):
            if action == self.COPY:
                self._copy(files)
            else:
                self._remove(files)

    def _missing(self):
        """The relpaths of src's files that dst lacks, each dir's together, sorted. Two local dirs
        are diffed with dirdiff, which scans them anew (so dirdelta needn't keep their trees, and
        its diff isn't from a stale scan), warning if find couldn't read everything; other trees
        are diffed as they are."""
        if not (isinstance(self._src, localdiskdirtree.LocalDiskDirTree) and
                isinstance(self._dst, localdiskdirtree.LocalDiskDirTree)):
            missing = self._dst.get_unknown_entries_in_given_dirtree(self._src)
            # By path components, so a dir's files and subdirs stay together
            return sorted((entry.relpath for entry in missing.iter_files()),
                          key=lambda relpath: relpath.split('/'))
        relpaths, errors = dirdiff.files_not_in(self._src.fullpath(), self._dst.fullpath(),
                                                self._src.max_depth)
        warning = localdiskdirtree.scan_warning(
            "%s or %s" % (self._src.fullpath(), self._dst.fullpath()), errors)
        if warning:
            messages.show("Warning: find couldn't read everything", warning, dryrun.label(), 'red')
        return relpaths

    def _chooseFiles(self, missing, action, picked=None):
        purpose = ("copy to %s" % (self._dst.fullpath(),) if action == self.COPY else
                   "remove from %s" % (self._src.fullpath(),))
        tree_header = ("Files in %s, which are not in %s. Pick the ones to %s:\n"
                       "(To select a file, press Space. When finished, press Enter.)" %
                       (self._src.fullpath(), self._dst.fullpath(), purpose))
        return picker.pick_files(self._src.fullpath(), missing, header=tree_header, picked=picked)

    def _file_entry(self, relpath):
        """The entry of src's file at relpath, for copying or removing it"""
        return entries.FileEntry(os.path.basename(relpath), relpath,
                                 os.path.join(self._src.fullpath(), relpath))

    def _confirm(self, action, relpaths):
        if action == self.COPY:
            question = "Copy %d files from %s to %s?" % (len(relpaths), self._src.fullpath(),
                                                         self._dst.fullpath())
        else:
            question = "Remove %d files from %s?" % (len(relpaths), self._src.fullpath())
        lines = [question] + ["  %s" % (relpath,) for relpath in relpaths[:self.MAX_FILES_LISTED]]
        if len(relpaths) > self.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(relpaths) - self.MAX_FILES_LISTED,))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines))
        return answer == self.CONFIRM_YES

    def _copy(self, files):
        _dirtree = dirtree.DirTree.from_file_entries(files, self._src.fullpath())
        # It adds what it copies to dst's tree, so the next diff doesn't list them
        self._dst.copy_inner_entries_from_dirtree(_dirtree)

    def _remove(self, files):
        self._src.remove_files(files)
