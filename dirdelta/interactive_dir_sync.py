import collections
import functools
import os

from googleapiclient.errors import HttpError

from dirdelta import clouddirtree
from dirdelta import dirdiff
from dirdelta import drivecache
from dirdelta import dirtree
from dirdelta import elsewhere
from dirdelta import entries
from dirdelta import dryrun
from dirdelta import hashes_screen
from dirdelta import hashing
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


def is_local(replica):
    return isinstance(replica, localdiskdirtree.LocalDiskDirTree)


def is_writable(replica):
    """Whether files can be copied into the replica, removed from it and moved in it: Drive, or a
    local dir with write permission (none on a read-only mount)"""
    return not is_local(replica) or os.access(replica.fullpath(), os.W_OK)


def can_copy(src, dst):
    """Whether src's files can be copied into dst: between a local dir and anything (not within
    Drive), into a writable one"""
    return is_writable(dst) and (is_local(src) or is_local(dst))


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


class InteractiveDirSync(object):
    """The files in src that aren't in dst, which the user picks and then copies to dst, removes
    from src, or renames to match where the other replica has them (see elsewhere.py), again and
    again, until they're done."""
    COPY = 'copy'
    REMOVE = 'remove'
    # Moving dst's files of the same names to the picked files' paths, or the picked files to
    # theirs
    RENAME_IN_DST = 'rename in dst'
    RENAME_IN_SRC = 'rename in src'
    # The label of each action's confirmation, so what it's for shows at a glance (magenta, not
    # red: red is LIVE's)
    LABELS = {COPY: ('COPY', 'blue'), REMOVE: ('REMOVE', 'magenta'),
              RENAME_IN_DST: ('RENAME', 'cyan'), RENAME_IN_SRC: ('RENAME', 'cyan')}

    # The action menu's first option, so it's the one selected at first: doing nothing
    NOTHING = "Nothing: back to the files"
    # The confirmations' options: No first, so it's the one selected at first
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    # The second confirmation of a removal's
    CONFIRM_SURE = 'Yes, remove them'
    # How many of the picked files the confirmation lists
    MAX_FILES_LISTED = 5
    # The file picker's key that reads the selected folder anew from Drive, when a replica is Drive's
    REFRESH_KEY = 'r'

    def __init__(self, src, dst, missing=None, src_index=None, dst_index=None, checked=None, changes=None):
        """missing: a future (concurrent.futures.Future) of find_missing(src, dst), e.g. found in
        the background, to use rather than finding it again. src_index, dst_index: the replicas'
        elsewhere.Index, kept by the caller so they're built once, and kept up to date here.
        checked: which of src's files' matches have the same contents (see
        elsewhere.check_contents()), kept by the caller too, so each is compared once."""
        self._src = src
        self._dst = dst
        self._missing_future = missing
        self.src_index = src_index or elsewhere.Index(src)
        self.dst_index = dst_index or elsewhere.Index(dst)
        self.checked = checked if checked is not None else {}
        # Where what's changed live is noted (a replicalog.Changes, by the replicas' displaynames),
        # for the entries of their logs, if anywhere
        self.changes = changes
        # Whether the replicas' files changed here (copied, removed, moved, or read anew from
        # Drive), so what each lacks may have
        self.has_changed = False

    def browse(self):
        """Let the user pick some of the files of src that dst lacks, then choose what to do with
        them (_act()): after that, or after choosing nothing, pick again, where they were, with the
        files done no longer there (or, in a dry run, no longer picked), until they quit."""
        missing = self._missing()
        if not missing:
            self._say_nothing()
            return
        clouds = [replica for replica in (self._src, self._dst)
                  if isinstance(replica, clouddirtree.CloudDirTree)]
        jobs = hashes_screen.jobs_of([self._src, self._dst])
        header = ("Files in %s, which are not in %s. Pick some, then choose what to do with them." %
                  (self._src.displayname(), self._dst.displayname()))
        keys = (self.REFRESH_KEY if clouds else '') + hashes_screen.KEY
        key_hints = ([('Enter', 'choose what to do')] +
                     ([(self.REFRESH_KEY, 'read the folder anew from Drive')] if clouds else []) +
                     [hashes_screen.KEY_HINT])
        picked, selected = [], None
        while True:
            src_job = hashing.job_for(self._src.fullpath()) if is_local(self._src) else None
            if src_job is not None:
                # The files shown first: they're the ones to compare
                src_job.first(missing)
            marks = hashes_screen.Marks(src_job, missing, jobs) if jobs else None
            try:
                chosen = picker.pick_files(
                    self._src.displayname(), missing, header=header, picked=picked,
                    keys=keys, selected=selected, shown_as=marks, key_hints=key_hints,
                    help_lines=hashes_screen.HELP_LINES if jobs else (),
                    previews=functools.partial(elsewhere.find_previews, missing, self._src, self.dst_index,
                                               checked=self.checked, src_index=self.src_index),
                    on_selection=functools.partial(elsewhere.check_contents, missing, self._src,
                                                   self.src_index, self.dst_index, self.checked))
            finally:
                if marks is not None:
                    marks.close()
            if chosen is None:
                return
            selected = chosen.selected
            if chosen.key == hashes_screen.KEY:
                hashes_screen.dashboard([self._src, self._dst])
                picked = chosen.files
                continue
            if chosen.key == self.REFRESH_KEY:
                done = []
                for replica in clouds:
                    if refresh_replica(replica, selected):
                        self.has_changed = True
                        self._index_of(replica).invalidate()
                        # Its files may have other contents now
                        self.checked.clear()
                is_changed = self.has_changed
            else:
                done = self._act(chosen.files)
                if done is None:
                    picked = chosen.files
                    continue
                is_changed = bool(done) and not dryrun.DRYRUN
                self.has_changed = self.has_changed or is_changed
            if is_changed:
                # Diffed anew (the trees as they are now: no background finding)
                self._missing_future = None
                missing = self._missing()
                if not missing:
                    self._say_nothing()
                    return
            still_missing = set(missing)
            done = set(done)
            picked = [relpath for relpath in chosen.files if relpath in still_missing and relpath not in done]
            selected = _shown(selected, missing)

    def _index_of(self, replica):
        return self.src_index if replica is self._src else self.dst_index

    def _say_nothing(self):
        messages.show("Nothing to do",
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

    def _act(self, relpaths):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (in a dry run, the ones it would have done), or None if the
        user chose nothing (or didn't confirm)."""
        if not self.dst_index.is_built():
            messages.print_line("Looking for files of the same names in %s..." % (self._dst.displayname(),))
        # The ones that may be in dst, moved or renamed: their contents are compared before a Rename
        may_be_there = elsewhere.may_be_elsewhere(relpaths, self._src, self.dst_index, self.checked,
                                                  self.src_index)
        nr_renamed_in_src = sum(1 for relpath in may_be_there if self._src.cant_move(relpath) is None)
        src_name, dst_name = self._src.displayname(), self._dst.displayname()
        count = _files(len(relpaths))
        options = {
            self.COPY: ("Copy the %s to %s" % (count, dst_name),
                        None if can_copy(self._src, self._dst) else
                        "can't: %s" % ("it's read-only" if not is_writable(self._dst) else
                                       "both are Google Drive's",)),
            self.REMOVE: ("Remove the %s from %s" % (count, src_name),
                          None if is_writable(self._src) else "can't: it's read-only"),
            # Each counts the picked files that may be in dst, moved or renamed. The replica last,
            # as in the others, so a long path doesn't hide what it does.
            self.RENAME_IN_DST: ("Rename the files matching %s of these to these paths, in %s" %
                                 (len(may_be_there), dst_name),
                                 self._cant_rename(self._dst, len(may_be_there))),
            self.RENAME_IN_SRC: ("Rename %s of these to their matches' paths, in %s" %
                                 (_files(nr_renamed_in_src), src_name),
                                 self._cant_rename(self._src, nr_renamed_in_src)),
        }
        disabled = {label: picker.Disabled("%s: %s" % (label, reason))
                    for label, reason in options.values() if reason is not None}
        header = ("%s picked in %s, which %s lacks. What to do with them?" %
                  (count, src_name, dst_name))
        answer = picker.pick_option([self.NOTHING] + [label for label, _ in options.values()],
                                    header=header, shown_as=lambda: disabled, title="What to do")
        action = next((action for action, (label, _) in options.items() if label == answer), None)
        if action is None:
            return None
        if action in (self.RENAME_IN_DST, self.RENAME_IN_SRC):
            moves = self._renames(action, may_be_there)
            return None if moves is None else self._rename(action, moves)
        if not self._confirm(action, relpaths):
            return None
        files = [self._file_entry(relpath) for relpath in relpaths]
        if action == self.COPY:
            title = "Copying %s from %s to %s" % (count, src_name, dst_name)
        else:
            title = "Removing %s from %s" % (count, src_name)
        if dryrun.DRYRUN:
            title += " (a dry run)"
        with messages.progress_screen(title, dryrun.label()):
            if action == self.COPY:
                self._copy(files)
            else:
                self._remove(files)
        if dryrun.DRYRUN:
            return relpaths
        if action == self.COPY:
            done = [relpath for relpath in relpaths if self._dst.has_file(relpath)]
            for relpath in done:
                self.dst_index.add(relpath, self._src.file_size(relpath))
            self._note(self._dst, 'copied', len(done), self._src.displayname())
        else:
            done = [relpath for relpath in relpaths if not self._src.has_file(relpath)]
            for relpath in done:
                self.src_index.remove(relpath)
            self._note(self._src, 'removed', len(done))
        return done

    def _note(self, replica, verb, count, source=None):
        """Note a live change of the replica's files (see replicalog.Changes.note())"""
        if self.changes is not None:
            self.changes.note(replica.displayname(), verb, count, source)

    def _cant_rename(self, replica, count):
        if not is_writable(replica):
            return "can't: it's read-only"
        if not count:
            return "none of these may be there, moved or renamed"
        return None

    def _renames(self, action, relpaths):
        """The moves of a Rename (RENAME_IN_DST or RENAME_IN_SRC, see _rename()) of the picked files
        at relpaths, which may be in dst: their contents compared first, where they weren't (on a
        progress screen, stoppable), so each is moved only if its match is surely it. None if it's
        stopped, or none is (which is said)."""
        to_compare = elsewhere.to_check(relpaths, self._src, self.dst_index, self.checked)
        if to_compare:
            is_stopped = False
            with messages.progress_screen("Comparing the contents of %s with their matches in %s" %
                                          (_files(len(to_compare)), self._dst.displayname()),
                                          dryrun.label()):
                try:
                    elsewhere.check_all(to_compare, self._src, self.src_index, self.dst_index, self.checked,
                                        lambda number, count, relpath: messages.print_progress(
                                            "Comparing %d of %d: %s" % (number, count, relpath)))
                except KeyboardInterrupt:
                    messages.note_stopped()
                    is_stopped = True
                else:
                    messages.print_line("")
                    messages.print_line("Compared %s" % (_files(len(to_compare)),))
            if is_stopped:
                return None
        renames = elsewhere.sure_matches(relpaths, self._src, self.dst_index, self.checked, self.src_index)
        # Moving dst's matches to the picked files' paths, or the picked files to the matches'
        if action == self.RENAME_IN_DST:
            moves = [(match, relpath) for relpath, match in renames.items() if self._dst.cant_move(match) is None]
        else:
            moves = [(relpath, match) for relpath, match in renames.items() if self._src.cant_move(relpath) is None]
        if not moves:
            messages.show("Nothing to rename",
                          ["None of the %s is surely in %s, moved or renamed%s." %
                           (_files(len(relpaths)), self._dst.displayname(),
                            " (their contents were compared)" if to_compare else "")],
                          dryrun.label())
            return None
        return moves

    def _rename(self, action, moves):
        """Move files, each of moves (relpath, new_relpath), in dst (RENAME_IN_DST) or src, once the
        user confirms. Returns the picked files done (or that would have been, in a dry run), or None
        if the user didn't confirm."""
        replica, index = ((self._dst, self.dst_index) if action == self.RENAME_IN_DST else
                          (self._src, self.src_index))
        # The picked file of each move
        picked_of = {move: move[1] if action == self.RENAME_IN_DST else move[0] for move in moves}
        lines = ["Move %s in %s?" % (_files(len(moves)), replica.displayname())]
        # A whole dir's as one, then the rest one by one
        dir_moves, file_moves = replica.dir_moves(moves)
        listed = (["  %s/ -> %s/ (a dir, with its %s, moved as one)" % (dirpath, new_dirpath, _files(len(its_moves)))
                   for dirpath, new_dirpath, its_moves in dir_moves] +
                  ["  %s -> %s" % move for move in file_moves])
        lines += listed[:self.MAX_FILES_LISTED]
        if len(listed) > self.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(listed) - self.MAX_FILES_LISTED,))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                                    label=self.LABELS[action], title="Sure?")
        if answer != self.CONFIRM_YES:
            return None
        title = "Moving %s in %s" % (_files(len(moves)), replica.displayname())
        if dryrun.DRYRUN:
            title += " (a dry run)"
        with messages.progress_screen(title, dryrun.label()):
            done = replica.move_files(moves)
        if dryrun.DRYRUN:
            return [picked_of[move] for move in moves]
        for relpath, new_relpath in done:
            index.move(relpath, new_relpath)
        self._note(replica, 'moved', len(done))
        return [picked_of[move] for move in done]

    def _file_entry(self, relpath):
        """The entry of src's file at relpath, for copying or removing it"""
        return entries.FileEntry(os.path.basename(relpath), relpath,
                                 os.path.join(self._src.fullpath(), relpath))

    def _confirm(self, action, relpaths):
        """Whether the user confirms copying or removing the files at relpaths; a removal, twice"""
        if action == self.COPY:
            question = "Copy %s from %s to %s?" % (_files(len(relpaths)), self._src.displayname(),
                                                   self._dst.displayname())
        else:
            question = "Remove %s from %s?" % (_files(len(relpaths)), self._src.displayname())
        lines = [question] + ["  %s" % (relpath,) for relpath in relpaths[:self.MAX_FILES_LISTED]]
        if len(relpaths) > self.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(relpaths) - self.MAX_FILES_LISTED,))
        lines += (self._src.copy_notes(relpaths) if action == self.COPY else
                  self._src.removal_notes(relpaths))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                                    label=self.LABELS[action], title="Sure?")
        if answer != self.CONFIRM_YES:
            return False
        if action == self.REMOVE:
            sure = ["Are you sure? %s will be removed from %s%s." %
                    (_files(len(relpaths)), self._src.displayname(),
                     " (to Drive's trash)" if not is_local(self._src) else ", for good")]
            answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_SURE], header='\n'.join(sure),
                                        label=self.LABELS[action], title="Sure?")
            return answer == self.CONFIRM_SURE
        return True

    def _copy(self, files):
        _dirtree = dirtree.DirTree.from_file_entries(files, self._src.fullpath())
        # It adds what it copies to dst's tree, so the next diff doesn't list them
        self._dst.copy_inner_entries_from_dirtree(_dirtree, self._src)

    def _remove(self, files):
        self._src.remove_files(files)


def _shown(relpath, missing):
    """relpath (a picker's selection), or the closest dir above it that the picker of missing (files)
    still shows ('' the root), if it's gone"""
    while relpath:
        prefix = relpath + '/'
        if any(path == relpath or path.startswith(prefix) for path in missing):
            return relpath
        relpath = os.path.dirname(relpath)
    return relpath
