import collections
import contextlib
import functools
import os

from googleapiclient.errors import HttpError

from dirdelta import ai
from dirdelta import aiplan
from dirdelta import aiplan_screen
from dirdelta import archive_screen
from dirdelta import archives
from dirdelta import clouddirtree
from dirdelta import contextmenu
from dirdelta import dirdiff
from dirdelta import drivecache
from dirdelta import elsewhere
from dirdelta import entries
from dirdelta import filescreen
from dirdelta import dryrun
from dirdelta import hashes_screen
from dirdelta import hashing
from dirdelta import localdiskdirtree
from dirdelta import paths
from dirdelta import messages
from dirdelta import opening
from dirdelta import picker
from dirdelta import renaming
from dirdelta import replicanames
from dirdelta import sidetree
from dirdelta import text


# The relpaths of the files in a dir that another lacks (see find_missing()), and the lines of a
# warning if scanning couldn't read everything, so the diff may be wrong (or none)
Missing = collections.namedtuple('Missing', ['relpaths', 'warning'])


def find_missing(src, dst):
    """The files of src that dst lacks (Missing), each dir's together, sorted. Two local dirs are
    diffed with dirdiff, which scans them anew (so dirdelta needn't keep their trees, and its diff
    isn't from a stale scan); other trees are diffed as they are. Shows nothing, so it can run in
    the background. What dirdelta keeps in a replica (its paths.META_DIR) isn't one of its files."""
    missing = _find_missing(src, dst)
    return Missing([relpath for relpath in missing.relpaths if not paths.is_meta(relpath)], missing.warning)


def _find_missing(src, dst):
    if not (localdiskdirtree.is_local(src) and localdiskdirtree.is_local(dst)):
        missing = dst.get_unknown_entries_in_given_dirtree(src)
        # By path components, so a dir's files and subdirs stay together
        return Missing(sorted((entry.relpath for entry in missing.iter_files()),
                              key=lambda relpath: relpath.split('/')), [])
    relpaths, errors = dirdiff.files_not_in(src.fullpath(), dst.fullpath(), src.max_depth)
    return Missing(relpaths, localdiskdirtree.scan_warning(
        "%s or %s" % (src.fullpath(), dst.fullpath()), errors))


def scan_errors_warning(tree):
    """A warning's lines if scanning the (local) tree couldn't read everything; else none."""
    return localdiskdirtree.scan_warning(tree.fullpath(), getattr(tree, 'scan_errors', []))


def rescan_replica(replica):
    """Scan the local replica anew, on a screen, saying if it couldn't read everything. Returns whether
    it was; if not (stopped, or it isn't there), it's as it was."""
    name = replica.fullpath()
    is_done, error = False, None
    with messages.progress_screen("Rescanning %s" % (name,), dryrun.label(), wait=False):
        try:
            replica.rescan()
            is_done = True
        except OSError as failure:
            error = failure
    if error is not None:
        messages.show("Couldn't rescan it", [str(error)], dryrun.label(), 'red')
    warning = scan_errors_warning(replica) if is_done else []
    if warning:
        messages.show("Warning: couldn't read everything", warning, dryrun.label(), 'red')
    return is_done


def _read_anew(replica, relpath):
    """Read the replica anew (on Drive, its folder at relpath). Returns whether it was."""
    if isinstance(replica, clouddirtree.CloudDirTree):
        return refresh_replica(replica, relpath)
    return localdiskdirtree.is_local(replica) and rescan_replica(replica)


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


is_local = localdiskdirtree.is_local


def is_writable(replica):
    """Whether files can be copied into the replica, removed from it and moved in it: Drive, or a
    local dir with write permission (none on a read-only mount)"""
    return not is_local(replica) or os.access(replica.fullpath(), os.W_OK)


def can_copy(src, dst):
    """Whether src's files can be copied into dst: between a local dir and anything (not within
    Drive), into a writable one"""
    return is_writable(dst) and (is_local(src) or is_local(dst))


_files = text.files


class InteractiveDirSync(filescreen.FilesScreen):
    """The files in src that aren't in dst, which the user picks and then copies to dst, removes
    from src, or renames to match where the other replica has them (see elsewhere.py), again and
    again, until they're done."""
    COPY = 'copy'
    REMOVE = 'remove'
    # Moving dst's files of the same names to the picked files' paths, or the picked files to
    # theirs
    RENAME_IN_DST = 'rename in dst'
    RENAME_IN_SRC = 'rename in src'
    # What the picker's keys do on the selected file, in the menu too: opening it (Ctrl-X), reading
    # its folder anew from Drive (r)
    OPEN = 'open'
    READ_ANEW = 'read anew'
    ASK_AI = 'ask AI'
    EXPLORE = 'explore'
    # The picker's keys that do an option of the menu, shown before it
    # (Ctrl-X opens the selected one, not the picked ones: Open has no key)
    SHORTCUTS = {READ_ANEW: 'Ctrl-R', ASK_AI: aiplan_screen.KEY_NAME, EXPLORE: archive_screen.KEY_NAME}
    # The label of each action's confirmation, so what it's for shows at a glance (magenta, not
    # red: red is LIVE's)
    LABELS = {COPY: ('COPY', 'blue'), REMOVE: ('REMOVE', 'magenta'),
              RENAME_IN_DST: ('RENAME', 'cyan'), RENAME_IN_SRC: ('RENAME', 'cyan')}

    # The action menu's first option, so it's the one selected at first: doing nothing
    NOTHING = "Nothing: back to the files"
    # The key that removes what's selected in the tree beside the picker (dst's)
    SIDE_REMOVE_KEY = 'd'

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
        # The action menu's last action done (see browse())
        self._last_action = None
        self.checked = checked if checked is not None else {}
        # Where what's changed live is noted (a replicalog.Changes, by the replicas' displaynames),
        # for the entries of their logs, if anywhere
        self.changes = changes
        # Whether the replicas' files changed here (copied, removed, moved, or read anew from
        # Drive), so what each lacks may have
        self.has_changed = False
        # Opens src's files (Ctrl-X, or Open in the action menu)
        self._opener = opening.Opener(src)
        # What the AI was last asked (see _ask_ai()), to start from next time
        self._last_instruction = ''
        # dst's dirs and files, for the tree beside the picker
        self._side_listing = sidetree.Listing(
            dst.displayname() if isinstance(dst, clouddirtree.CloudDirTree) else dst.fullpath(), dst)

    def browse(self):
        """See _browse(); what it kept of dst is let go after"""
        try:
            self._browse()
        finally:
            self._side_listing.close()

    def _browse(self):
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
        src_name, dst_name = (replicanames.full(replica.displayname() if not is_local(replica) else replica.fullpath())
                              for replica in (self._src, self._dst))
        header = "%s lacks these. Pick some, then choose what to do with them." % (dst_name,)
        keys = self.REFRESH_KEY + hashes_screen.KEY + aiplan_screen.KEY + contextmenu.KEY + archive_screen.KEY
        # The keys row has little room: the rest are in the menu (:), and ?
        key_hints = [('Enter', 'choose what to do'), contextmenu.KEY_HINT]
        more_keys = ([aiplan_screen.KEY_HINT, archive_screen.KEY_HINT, opening.KEY_HINT, renaming.KEY_HINT,
                      ('Ctrl-W l', 'move to %s, on the right (Ctrl-W h: back)' % (dst_name,)),
                      (self.SIDE_REMOVE_KEY + ' there', 'remove what\'s selected there'),
                      ('Enter, : there', 'choose what to do with it')] +
                     [(self.REFRESH_KEY_NAME, ('read the folder anew from Drive, ' if clouds else '') + 'list the tree on the right anew'),
                      hashes_screen.KEY_HINT])
        picked, selected = [], None
        # Where to go on in the side tree, after what was done there
        side_start = None
        while True:
            src_job = hashing.job_for(self._src.fullpath()) if is_local(self._src) else None
            if src_job is not None:
                # The files shown first: they're the ones to compare
                src_job.first(missing)
            marks = hashes_screen.Marks(src_job, missing, jobs, extra=self._opener.status_parts) if jobs else None
            files = set(missing)
            shown_before = missing

            def shown_as(marks=marks, src_job=src_job):
                """The hashing tags (Marks), and the downloads' to open the files (opening.py)"""
                shown = marks() if marks is not None else {'': picker.segments(self._opener.status_parts())}
                return opening.with_tags(shown, self._opener, lambda relpath: (
                    marks.text(relpath) if marks is not None else os.path.basename(relpath)))
            try:
                chosen = picker.pick_files(
                    src_name, missing, header=header, picked=picked,
                    keys=keys, selected=selected, key_hints=key_hints,
                    shown_as=shown_as, notify_keys=opening.KEY, twice_keys=renaming.KEY,
                    # dst beside it, to look through (e.g. for a newer version of a file)
                    side=picker.Side(dst_name, self._side_items(), True, self._side_follow,
                                     self.SIDE_REMOVE_KEY + contextmenu.KEY + self.REFRESH_KEY,
                                     [('Enter', 'choose what to do'), (self.SIDE_REMOVE_KEY, 'remove'), contextmenu.KEY_HINT,
                                      (self.REFRESH_KEY_NAME, filescreen.SIDE_REFRESH_HINTS[self._dst in clouds])],
                                     side_start),
                    enter_picks_selection=True,
                    none_picked_key_hints=[('Enter', 'Pick & choose what to do')],
                    # Ctrl-X opens the selected one (the picked ones: the menu's Open)
                    on_notify=lambda key, selected, picked: self._opener.press([selected], files),
                    help_lines=picker.key_help_lines(more_keys) + (hashes_screen.HELP_LINES if jobs else []),
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
            side_start = chosen.side_selected if chosen.key == picker.SIDE_KEY else None
            chosen, left_picked = self._shared_key(chosen, missing)
            if chosen is None:
                picked = left_picked
                continue
            key = chosen.key
            # What the action menu's action was (Copy and Remove change only the files they do)
            self._last_action = None
            # Ctrl-R there reads dst anew (on Drive, what's selected there); here, each replica (on Drive,
            # what's selected here)
            to_refresh = [(replica, selected) for replica in (self._src, self._dst)]
            if key == picker.SIDE_KEY and chosen.side_pressed == self.REFRESH_KEY:
                key = self.REFRESH_KEY
                to_refresh = [(self._dst, chosen.side_selected)]
            if key == renaming.PRESSED:
                picked = chosen.files
                renamed = self._rename_selected(selected)
                if renamed is None:
                    continue
                new_relpath, moves = renamed
                missing = self._missing()
                if not missing:
                    self._say_nothing()
                    return
                moved = dict(moves)
                still_missing = set(missing)
                picked = [moved.get(relpath, relpath) for relpath in chosen.files
                          if moved.get(relpath, relpath) in still_missing]
                selected = filescreen.shown_near(new_relpath, missing)
                continue
            if key == aiplan_screen.KEY:
                # About the picked ones, or with none picked, all of them: the AI picks (and it's told
                # where the selection is)
                done = self._ask_ai(chosen.files or missing,
                                    chosen.files or (contextmenu.under(missing, selected) if selected else []))
            elif key == picker.SIDE_KEY:
                done = self._act_in_dst(chosen.side_selected, chosen.side_pressed == self.SIDE_REMOVE_KEY)
            elif not key:
                done = self._act(chosen.files, selected)
                if done is filescreen.READ_ANEW:
                    key = self.REFRESH_KEY
            if key == self.REFRESH_KEY:
                done = []
                # What changed outside dirdelta shows there now
                self._side_listing.invalidate()
                for replica, relpath in to_refresh:
                    if _read_anew(replica, relpath):
                        self.has_changed = True
                        self._index_of(replica).invalidate()
                        # Its files may have other contents now
                        self.checked.clear()
                        for job in hashes_screen.jobs_of([replica]):
                            job.scan_in_background()
                is_changed = self.has_changed
            else:
                if done is None:
                    picked = chosen.files
                    continue
                is_changed = bool(done) and not dryrun.DRYRUN
                self.has_changed = self.has_changed or is_changed
            if is_changed and self._last_action in (self.COPY, self.REMOVE):
                # Only the ones done aren't missing now (copied to dst, or removed from src): no
                # need to diff the replicas anew, which for local ones scans them both
                done_now = set(done)
                missing = [relpath for relpath in missing if relpath not in done_now]
                if not missing:
                    self._say_nothing()
                    return
            elif is_changed:
                # Diffed anew (the trees as they are now: no background finding)
                self._missing_future = None
                missing = self._missing()
                if not missing:
                    self._say_nothing()
                    return
            still_missing = set(missing)
            done = set(done)
            picked = [relpath for relpath in chosen.files if relpath in still_missing and relpath not in done]
            selected = filescreen.shown_near(selected, missing, shown_before)

    def _dashboard(self):
        hashes_screen.dashboard([self._src, self._dst])

    def _menu_key(self, answer, selected, files):
        if answer == opening.KEY:
            self._opener.press([selected], set(files))
            return True
        return False

    def _context_menu(self, selected, missing):
        """What to do with nothing picked, on the picker's selected relpath (see contextmenu.py): what
        its keys do, as the key's returned, a contextmenu.PICK or WHAT_TO_DO, or None"""
        name = contextmenu.selected_name(selected)
        is_file = selected in set(missing)
        clouds = [replica for replica in (self._src, self._dst) if isinstance(replica, clouddirtree.CloudDirTree)]
        entries = [contextmenu.Entry(None, "Choose what to do with %s" % (name,), contextmenu.WHAT_TO_DO),
                   contextmenu.Entry('Space', "Pick %s" % (name,), contextmenu.PICK),
                   contextmenu.Entry(aiplan_screen.KEY_NAME, "Ask AI what to do with all the files, and review its plan",
                                     aiplan_screen.KEY)]
        if is_file and archives.is_archive(selected):
            entries.append(contextmenu.Entry(archive_screen.KEY_NAME, "Explore %s" % (name,), archive_screen.KEY))
        if is_file:
            entries.append(contextmenu.Entry(opening.KEY_HINT[0], "Open %s with its program" % (name,), opening.KEY))
        if selected:
            entries.append(contextmenu.Entry(renaming.KEY_HINT[0], "Rename %s" % (name,), renaming.PRESSED))
        if clouds:
            entries.append(contextmenu.Entry(self.REFRESH_KEY_NAME, "Read %s/ anew from Google Drive" % (
                os.path.dirname(selected) if is_file else selected or '.',), self.REFRESH_KEY))
        entries.append(contextmenu.Entry(hashes_screen.KEY, "Replicas dashboard", hashes_screen.KEY))
        return contextmenu.choose(entries, contextmenu.nothing_picked(len(missing)), side=self._dst.displayname())

    def _act_in_dst(self, relpath, is_removed=False):
        """Enter (or :) in the tree beside the picker, dst's, on the file or dir at relpath: choose what
        to do with it there, e.g. to remove a version of a repository that src has another of, then
        copy that one; with is_removed (d there), it's to remove it. Returns the files done (none in a dry run), or None if none were: then dst is diffed anew,
        as its files changed."""
        name = self._dst.displayname()
        if not relpath:
            messages.show("That's all of %s" % (name,), ["Select a file or dir in it."], dryrun.label())
            return None
        if not self.dst_index.is_built():
            messages.print_line("Looking through %s..." % (name,))
        self.dst_index.build()
        files = [path for path in sorted(contextmenu.under(self.dst_index.relpaths(), relpath))
                 if not paths.is_meta(path)]
        if not files:
            messages.show("Nothing to remove", ["%s has no files." % (relpath,)], dryrun.label())
            return None
        remove = "Remove %s (%s) from %s" % (relpath, _files(len(files)), name)
        shown = {} if is_writable(self._dst) else {remove: picker.Disabled("%s: can't, it's read-only" % (remove,))}
        if is_removed and shown:
            messages.show("Can't remove it", ["%s is read-only." % (name,)], dryrun.label())
            return None
        answer = remove if is_removed else picker.pick_option(
            [self.NOTHING, remove], header="%s, in %s: what to do with it?" % (relpath, name),
            shown_as=lambda: shown, title="What to do")
        if answer != remove or not self._confirm(self.REMOVE, files, replica=self._dst):
            return None
        title = "Removing %s from %s%s" % (_files(len(files)), name, " (a dry run)" if dryrun.DRYRUN else "")
        with messages.progress_screen(title, dryrun.label()):
            self._dst.remove_files([entries.FileEntry(os.path.basename(path), path,
                                                      os.path.join(self._dst.fullpath(), path)) for path in files])
        if dryrun.DRYRUN:
            return []
        done = [path for path in files if not self._dst.has_file(path)]
        # What src's files were compared with may be gone
        self.checked.clear()
        self._note(self._dst, 'removed', len(done))
        return done

    def _explore(self, relpath, files):
        """e: look in src's zip at relpath (see archive_screen.py)"""
        archive_screen.explore(relpath, files, lambda: self._opener.local_path(relpath))

    def _rename_selected(self, selected):
        """cc: rename src's file or dir at selected (see renaming.py). Returns (its new relpath, the
        files' moves), once it's renamed (then src is diffed anew), or None (as in a dry run)."""
        renamed = renaming.rename(self._src, selected)
        if renamed is None or dryrun.DRYRUN:
            return None
        new_relpath, moves = renamed
        for relpath, new in moves:
            # Compared under its old path
            self.checked.pop(relpath, None)
        self._note(self._src, 'moved', len(moves))
        self.has_changed = True
        self._missing_future = None
        # Its hashes are kept under the new paths: the job lists them there
        for job in hashes_screen.jobs_of([self._src]):
            job.scan_in_background()
        return new_relpath, moves

    def _side_items(self):
        """dst's dirs and files, for the tree beside the picker (see sidetree.py)"""
        return self._side_listing.items()

    def _side_follow(self, relpath):
        """Where in dst src's file at relpath is related to, for the tree beside the picker: a file
        of its name there (the first, by path), or else its own path (the closest dir dst has)"""
        if self.dst_index.is_built():
            named = self.dst_index.files_named(os.path.basename(relpath))
            if named:
                return sorted(named)[0]
        return relpath

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
            messages.show("Warning: couldn't read everything", missing.warning, dryrun.label(),
                          'red')
        return missing.relpaths

    def _act(self, relpaths, selected=None):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (in a dry run, the ones it would have done), or None if the
        user chose nothing (or didn't confirm, or opened them); or filescreen.READ_ANEW to read the folder of
        selected (the picker's selection, a file or a dir; by default the first file) anew from
        Drive, as the key does."""
        if selected is None:
            selected = relpaths[0]
        clouds = [replica for replica in (self._src, self._dst) if isinstance(replica, clouddirtree.CloudDirTree)]
        folder = os.path.dirname(selected) if self._src.has_file(selected) else selected
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
        options[self.ASK_AI] = ("Ask AI what to do with %s, and review its plan" %
                                ("it" if len(relpaths) == 1 else "the " + count,), None)
        if len(relpaths) == 1 and archives.is_archive(relpaths[0]):
            options[self.EXPLORE] = ("Explore it: what's in the zip", None)
        options[self.OPEN] = ("Open %s with %s program%s" %
                              ("it" if len(relpaths) == 1 else "the " + count,
                               "its" if len(relpaths) == 1 else "their", "" if len(relpaths) == 1 else "s"),
                              None if len(relpaths) <= opening.MAX_OPENED else
                              "can't: more than %d at once" % (opening.MAX_OPENED,))
        if clouds:
            options[self.READ_ANEW] = ("Read %s anew from Google Drive" %
                                       (' and '.join(os.path.join(replica.displayname(), folder).rstrip('/') + '/'
                                                     for replica in clouds),), None)
        # After its key, if a picker's key does it too
        prefixes = picker.shortcut_prefixes([self.NOTHING] + [label for label, _ in options.values()],
                                            {label: self.SHORTCUTS[action] for action, (label, _) in options.items()
                                             if action in self.SHORTCUTS})
        def option(action):
            label, reason = options[action]
            return picker.Option(action, label, prefixes[label] + label if reason is None else
                                 picker.Disabled(picker.unstyled(prefixes[label]) + "%s: %s" % (label, reason)))
        # Similar actions together, a blank line between each kind
        kinds = [[self.ASK_AI], [self.COPY], [self.REMOVE], [self.RENAME_IN_DST, self.RENAME_IN_SRC], [self.EXPLORE, self.OPEN, self.READ_ANEW]]
        choices = picker.grouped([[picker.Option(self.NOTHING, self.NOTHING, prefixes[self.NOTHING] + self.NOTHING)]] +
                                 [[option(action) for action in kind if action in options] for kind in kinds])
        header = ("%s picked in %s, which %s lacks. What to do with them?" %
                  (count, src_name, dst_name))
        action = picker.pick_option(choices, header=header, title="What to do")
        if action not in options:
            return None
        if action == self.OPEN:
            if opening.confirm(self._opener, relpaths, relpaths):
                self._opener.open_in_background(relpaths, relpaths)
            return None
        if action == self.READ_ANEW:
            return filescreen.READ_ANEW
        if action in (self.RENAME_IN_DST, self.RENAME_IN_SRC):
            moves = self._renames(action, may_be_there)
            return None if moves is None else self._rename(action, moves)
        if action == self.ASK_AI:
            return self._ask_ai(relpaths, relpaths)
        if action == self.EXPLORE:
            self._explore(relpaths[0], set(relpaths))
            return None
        return self._copy_or_remove(action, relpaths)

    def _copy_or_remove(self, action, relpaths, to_trash=False):
        """Copy the files at relpaths to dst, or remove them from src (action), once the user confirms.
        Returns the ones done (in a dry run, the ones it would have done), or None if the user didn't
        confirm. With to_trash, a local src's go to the desktop's trash, rather than for good."""
        to_trash = to_trash and is_local(self._src)
        if not self._confirm(action, relpaths, to_trash):
            return None
        self._last_action = action
        src_name, dst_name = self._src.displayname(), self._dst.displayname()
        count = _files(len(relpaths))
        files = [self._file_entry(relpath) for relpath in relpaths]
        if action == self.COPY:
            title = "Copying %s from %s to %s" % (count, src_name, dst_name)
        else:
            title = "Removing %s from %s" % (count, src_name)
        if dryrun.DRYRUN:
            title += " (a dry run)"
        with messages.progress_screen(title, dryrun.label()), (self._src.trashing() if to_trash else
                                                               contextlib.nullcontext()):
            if action == self.COPY:
                self._copy(files)
            else:
                self._remove(files)
        if dryrun.DRYRUN:
            return relpaths
        if action == self.COPY:
            done = [relpath for relpath in relpaths if self._dst.has_file(relpath)]
            self._note(self._dst, 'copied', len(done), self._src.displayname())
        else:
            done = [relpath for relpath in relpaths if not self._src.has_file(relpath)]
            self._note(self._src, 'removed', len(done))
        return done

    def _ai_task(self, relpaths, focus):
        """What to ask the AI about src's files at relpaths, the user being on those of focus (see
        aiplan.py): dst's files are told too, to rename them, and each's copies there, as far as it's
        known"""
        src_name, dst_name = self._src.displayname(), self._dst.displayname()

        def can_rename(replica):
            def check(relpath, target):
                return replica.cant_move(relpath) or ("there's a file there already" if _exists(replica, target) else None)
            return check
        actions = []
        if can_copy(self._src, self._dst):
            actions.append(aiplan.Action(self.COPY, "Copy to destination",
                                         "copy the file to %s, to the same path." % (dst_name,)))
        if is_writable(self._src):
            actions.append(aiplan.Action(self.RENAME_IN_SRC, "Rename in source",
                                         "move or rename the file in %s." % (src_name,), True, False,
                                         can_rename(self._src)))
        if is_writable(self._dst):
            actions.append(aiplan.Action(self.RENAME_IN_DST, "Rename in destination",
                                         "move or rename one of %s's other files, in it (e.g. to the path of the "
                                         "same file in %s, so they match)." % (dst_name, src_name), True, True,
                                         can_rename(self._dst)))
        if is_writable(self._src):
            actions.append(aiplan.Action(self.REMOVE, "Remove from source",
                                         "remove the file from %s, which is then in neither." % (src_name,)))
        files = []
        for relpath in relpaths:
            same = [match for match, is_same in elsewhere.known_same(relpath, self.src_index, self.dst_index).items()
                    if is_same]
            files.append(aiplan.File(relpath, self._src.file_size(relpath),
                                     "the same contents as %s in %s" % (', '.join(sorted(same)[:3]), dst_name)
                                     if same else ''))
        others = sorted(relpath for relpath in self.dst_index.relpaths() if not paths.is_meta(relpath))
        return aiplan.Task("These are files in the source, %s, which the destination, %s, lacks at the same paths." %
                           (src_name, dst_name),
                           files, actions, others, focus=focus,
                           fetch=lambda relpath: self._opener.local_path(relpath, ai.MAX_READ_SIZE))

    def _ask_ai(self, relpaths, focus=()):
        """Ask the AI about src's files at relpaths, the user being on those of focus, and do what the
        user approves of its plan, if it answers with one (each kind once they confirm it, as if they
        chose it). Returns the files done (in a dry run,
        the ones it would have done), or None if none were."""
        messages.print_line("Looking through %s and %s..." % (self._src.displayname(), self._dst.displayname()))
        self.src_index.build()
        self.dst_index.build()
        self._last_instruction, steps = aiplan_screen.ask(self._ai_task(relpaths, focus), self._last_instruction)
        if not steps:
            return None
        done = []
        for action in (self.COPY, self.RENAME_IN_SRC, self.RENAME_IN_DST):
            moves = [(step.relpath, step.target) for step in aiplan_screen.of_action(steps, action) if step.target]
            if action == self.COPY:
                copied = [step.relpath for step in aiplan_screen.of_action(steps, action)]
                done += (self._copy_or_remove(action, copied) or []) if copied else []
            elif moves:
                done += self._rename(action, moves) or []
        removed = [step.relpath for step in aiplan_screen.of_action(steps, self.REMOVE)]
        if removed:
            # Which only src has: what the AI said to remove can be restored
            done += self._copy_or_remove(self.REMOVE, removed, to_trash=True) or []
        # Of several kinds: the replicas are diffed anew
        self._last_action = None
        return done or None

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
        replica = self._dst if action == self.RENAME_IN_DST else self._src
        # The picked file of each move
        picked_of = {move: move[1] if action == self.RENAME_IN_DST else move[0] for move in moves}
        lines = ["Move %s in %s?" % (_files(len(moves)), replica.displayname())]
        # A whole dir's as one, then the rest one by one
        dir_moves, file_moves = replica.dir_moves(moves)
        listed = (["  %s/ -> %s/ (a dir, with its %s, moved as one)" % (dirpath, new_dirpath, _files(len(its_moves)))
                   for dirpath, new_dirpath, its_moves in dir_moves] +
                  ["  %s -> %s" % move for move in file_moves])
        lines += text.listed(listed, self.MAX_FILES_LISTED)
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        answer = picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                                    label=self.LABELS[action], title="Sure?")
        if answer != self.CONFIRM_YES:
            return None
        title = "Moving %s in %s" % (_files(len(moves)), replica.displayname())
        if dryrun.DRYRUN:
            title += " (a dry run)"
        # Stopped (Ctrl-C) before move_files() says (it says how far it got, if it's stopped in it)
        done = []
        with messages.progress_screen(title, dryrun.label()):
            done = replica.move_files(moves)
        if dryrun.DRYRUN:
            return [picked_of[move] for move in moves]
        self._note(replica, 'moved', len(done))
        return [picked_of[move] for move in done]

    def _file_entry(self, relpath):
        """The entry of src's file at relpath, for copying or removing it"""
        return entries.FileEntry(os.path.basename(relpath), relpath,
                                 os.path.join(self._src.fullpath(), relpath))

    def _confirm(self, action, relpaths, to_trash=False, replica=None):
        """Whether the user confirms copying or removing the files at relpaths (of src, or the replica
        they're in, if it isn't); a removal, twice"""
        replica = replica or self._src
        if action == self.COPY:
            question = "Copy %s from %s to %s?" % (_files(len(relpaths)), self._src.displayname(),
                                                   self._dst.displayname())
        else:
            question = "Remove %s from %s?" % (_files(len(relpaths)), replica.displayname())
        lines = [question] + text.listed(["  %s" % (relpath,) for relpath in relpaths], self.MAX_FILES_LISTED)
        lines += (self._src.copy_notes(relpaths) if action == self.COPY else
                  replica.removal_notes(relpaths))
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, self.LABELS[action]):
            return False
        return action != self.REMOVE or self._is_sure(len(relpaths), replica.displayname(), not is_local(replica),
                                                      to_trash, self.LABELS[action])

    def _copy(self, files):
        # It adds what it copies to dst's tree, so the next diff doesn't list them
        self._dst.copy_in(files, self._src)

    def _remove(self, files):
        self._src.remove_files(files)


def _exists(replica, relpath):
    """Whether the replica has a file or dir at relpath"""
    return os.path.lexists(os.path.join(replica.fullpath(), relpath)) if is_local(replica) else replica.exists(relpath)
