import collections
import os

from googleapiclient.errors import HttpError

from dirdelta import clouddirtree
from dirdelta import dirdiff
from dirdelta import drivecache
from dirdelta import dirtree
from dirdelta import elsewhere
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


def refresh_replica(replica, relpath=''):
    """Read the cloud replica's folder at relpath (default: all of it) anew from Drive
    (CloudDirTree.refresh_from_drive()). Returns whether it was; if not, it's said why (on a screen),
    and the replica and the cache are as they were."""
    title = "Refresh %s from Google Drive" % (os.path.join(replica.displayname(), relpath).rstrip('/'),)
    try:
        replica.refresh_from_drive(relpath)
    except KeyboardInterrupt:
        messages.show(title, ["Stopped (Ctrl-C): the cloud files list cache is as it was."],
                      dryrun.label(), 'red')
    except (HttpError, OSError, drivecache.DriveCacheError) as error:
        messages.show(title, ["Couldn't refresh it: %s" % (error,)], dryrun.label(), 'red')
    else:
        return True
    return False


class InteractiveDirSync(object):
    """Copying or removing the files in src that aren't in dst, picked by the user."""
    COPY = 'copy'
    REMOVE = 'remove'
    # The label of the file picker and the confirmation, by action, so what the picks are for shows
    # at a glance (magenta, not red: red is LIVE's)
    LABELS = {COPY: ('COPY', 'blue'), REMOVE: ('REMOVE', 'magenta')}

    # The confirmation menu's options: No first, so it's the one selected at first
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    # How many of the picked files the confirmation lists
    MAX_FILES_LISTED = 5
    # The file picker's key that reads the selected folder anew from Drive, when a replica is Drive's
    REFRESH_KEY = 'r'

    def __init__(self, src, dst, missing=None):
        """missing: a future (concurrent.futures.Future) of find_missing(src, dst), e.g. found in
        the background, to use rather than finding it again"""
        self._src = src
        self._dst = dst
        self._missing_future = missing
        # Whether a replica was read anew from Drive (so what each lacks may have changed)
        self.was_refreshed = False

    def view_diff(self):
        """Show the files in src that aren't in dst"""
        missing = dirtree.DirTree(self._src.fullpath())
        for relpath in self._missing():
            missing.add_file_by_relpath(relpath)
        header = "Files in %s, which are not in %s:" % (self._src.displayname(),
                                                          self._dst.displayname())
        picker.pick_from_tree(missing, header=header, root_name=self._src.displayname())

    def sync(self, action):
        """Let the user pick files of src that aren't in dst, then copy them to dst (action COPY) or
        remove them from src (REMOVE), once the user confirms. If the user doesn't confirm, they pick
        again, starting from what they picked."""
        missing = self._missing()
        if not missing:
            self._say_nothing_to(action)
            return
        picked = None
        while True:
            picked, missing = self._chooseFiles(missing, action, picked)
            if not picked:
                return
            if self._confirm(action, picked):
                break

        files = [self._file_entry(relpath) for relpath in picked]
        if action == self.COPY:
            title = "Copying %d files from %s to %s" % (len(files), self._src.displayname(),
                                                       self._dst.displayname())
        else:
            title = "Removing %d files from %s" % (len(files), self._src.displayname())
        if dryrun.DRYRUN:
            title += " (a dry run)"
        with messages.progress_screen(title, dryrun.label()):
            if action == self.COPY:
                self._copy(files)
            else:
                self._remove(files)

    def _say_nothing_to(self, action):
        messages.show("Nothing to %s" % (action,),
                      ["%s has all of %s's files." % (self._dst.displayname(), self._src.displayname())],
                      dryrun.label())

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
        """Let the user pick some of the missing files (picked start picked). Returns them (or None,
        if the user quit) and what's missing, which a refresh (the REFRESH_KEY) changes: the picker
        comes back where it was, with what's still missing of the picks picked. Beside it, where dst
        has files of the selected file's name (see elsewhere.py), in case it's moved, not missing."""
        purpose = ("copy to %s" % (self._dst.displayname(),) if action == self.COPY else
                   "remove from %s" % (self._src.displayname(),))
        clouds = self._cloud_replicas()
        tree_header = ("Files in %s, which are not in %s. Pick the ones to %s:\n"
                       "(To select a file, press Space. When finished, press Enter.%s)" %
                       (self._src.displayname(), self._dst.displayname(), purpose,
                        " %s: read the selected folder anew from Google Drive." % (self.REFRESH_KEY,)
                        if clouds else ""))
        selected = None
        while True:
            chosen = picker.pick_files(self._src.displayname(), missing, header=tree_header,
                                       picked=picked, label=self.LABELS[action],
                                       keys=self.REFRESH_KEY if clouds else '', selected=selected,
                                       previews=self._previews(missing))
            if not isinstance(chosen, picker.KeyPressed):
                return chosen, missing
            selected = chosen.selected
            for replica in clouds:
                self.was_refreshed = refresh_replica(replica, selected) or self.was_refreshed
            # Diffed anew (the trees as they are now: no background finding)
            self._missing_future = None
            missing = self._missing()
            if not missing:
                self._say_nothing_to(action)
                return None, missing
            still_missing = set(missing)
            picked = [relpath for relpath in chosen.picked if relpath in still_missing]

    def _previews(self, missing):
        """The file picker's previews of the missing files: where dst has files of their names"""
        messages.print_line("Looking for files of the same names elsewhere in %s..." %
                            (self._dst.displayname(),))
        return elsewhere.previews(missing, self._src, self._dst)

    def _cloud_replicas(self):
        """The replicas that are Drive's, so can be read anew from it"""
        return [replica for replica in (self._src, self._dst)
                if isinstance(replica, clouddirtree.CloudDirTree)]

    def _file_entry(self, relpath):
        """The entry of src's file at relpath, for copying or removing it"""
        return entries.FileEntry(os.path.basename(relpath), relpath,
                                 os.path.join(self._src.fullpath(), relpath))

    def _confirm(self, action, relpaths):
        if action == self.COPY:
            question = "Copy %d files from %s to %s?" % (len(relpaths), self._src.displayname(),
                                                         self._dst.displayname())
        else:
            question = "Remove %d files from %s?" % (len(relpaths), self._src.displayname())
        lines = [question] + ["  %s" % (relpath,) for relpath in relpaths[:self.MAX_FILES_LISTED]]
        if len(relpaths) > self.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(relpaths) - self.MAX_FILES_LISTED,))
        lines += (self._src.copy_notes(relpaths) if action == self.COPY else
                  self._src.removal_notes(relpaths))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                                    label=self.LABELS[action])
        return answer == self.CONFIRM_YES

    def _copy(self, files):
        _dirtree = dirtree.DirTree.from_file_entries(files, self._src.fullpath())
        # It adds what it copies to dst's tree, so the next diff doesn't list them
        self._dst.copy_inner_entries_from_dirtree(_dirtree, self._src)

    def _remove(self, files):
        self._src.remove_files(files)
