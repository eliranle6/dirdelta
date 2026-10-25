import collections
import os

from dirdelta import dirdiff
from dirdelta import dirtree
from dirdelta import entries
from dirdelta import dryrun
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import picker


# The relpaths of the files in a dir that another lacks (see find_missing()), and the lines of a
# warning if scanning couldn't read everything, so the diff may be wrong (or none)
Missing = collections.namedtuple('Missing', ['relpaths', 'warning'])


def find_missing(src, dst):
    """The files of src that dst lacks (Missing), each dir's together, sorted. Two local dirs are
    diffed with dirdiff, which scans them anew (so dirdelta needn't keep their trees, and its diff
    isn't from a stale scan); other trees are diffed as they are. Shows nothing, so it can run in
    the background."""
    if not (isinstance(src, localdiskdirtree.LocalDiskDirTree) and
            isinstance(dst, localdiskdirtree.LocalDiskDirTree)):
        missing = dst.get_unknown_entries_in_given_dirtree(src)
        # By path components, so a dir's files and subdirs stay together
        return Missing(sorted((entry.relpath for entry in missing.iter_files()),
                              key=lambda relpath: relpath.split('/')), [])
    relpaths, errors = dirdiff.files_not_in(src.fullpath(), dst.fullpath(), src.max_depth)
    return Missing(relpaths, localdiskdirtree.scan_warning(
        "%s or %s" % (src.fullpath(), dst.fullpath()), errors))


class InteractiveDirSync(object):
    """Copying or removing the files in src that aren't in dst, picked by the user."""
    COPY = 'copy'
    REMOVE = 'remove'

    # The confirmation menu's options: No first, so it's the one selected at first
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    # How many of the picked files the confirmation lists
    MAX_FILES_LISTED = 5

    def __init__(self, src, dst, missing=None):
        """missing: a future (concurrent.futures.Future) of find_missing(src, dst), e.g. found in
        the background, to use rather than finding it again"""
        self._src = src
        self._dst = dst
        self._missing_future = missing

    def view_diff(self):
        """Show the files in src that aren't in dst"""
        missing = dirtree.DirTree(self._src.fullpath())
        for relpath in self._missing():
            missing.add_file_by_relpath(relpath)
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
        """The relpaths of src's files that dst lacks (see find_missing()), warning if scanning
        couldn't read everything"""
        if self._missing_future is not None:
            missing = self._missing_future.result()
        else:
            missing = find_missing(self._src, self._dst)
        if missing.warning:
            messages.show("Warning: find couldn't read everything", missing.warning, dryrun.label(),
                          'red')
        return missing.relpaths

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
