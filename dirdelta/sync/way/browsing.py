"""The sync's file picker: the loop that shows it and does what's chosen"""
from dirdelta.screens import aiplan_screen
from dirdelta.screens import hashes_screen
from dirdelta.sync import replica_ops
from dirdelta.sync.way.picking import Picking
from dirdelta.ui import contextmenu
from dirdelta.ui import filescreen
from dirdelta.ui import picker
from dirdelta.ui import renaming
from dirdelta.util import dryrun


class Browsing(Picking):
    """The picker, shown until it's quit (InteractiveDirSync's)"""

    def _browse(self):
        """Let the user pick some of the files of src that dst lacks, then choose what to do with
        them (_act()): after that, or after choosing nothing, pick again, where they were, with the
        files done no longer there (or, in a dry run, no longer picked), until they quit."""
        missing = self._listed()
        if not missing:
            self._say_nothing()
            return
        screen = self._picker_screen()
        picked, selected = [], None
        # Where to go on in the side tree, after what was done there
        side_start = None
        while True:
            shown_before = missing
            chosen, only_missing = self._pick(screen, missing, picked, selected, side_start)
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
            # Ctrl-R there reads dst anew (on Drive, what's selected there); here, what's on Drive (what's
            # selected here), and only without any on Drive, the local ones
            to_refresh = [(replica, selected) for replica in screen.clouds or (self._src, self._dst)]
            if key == picker.SIDE_KEY and chosen.side_pressed == self.REFRESH_KEY:
                key = self.REFRESH_KEY
                to_refresh = [(self._dst, chosen.side_selected)]
            if key == renaming.PRESSED:
                renamed = self._after_rename(chosen, selected)
                if renamed is None:
                    picked = chosen.files
                    continue
                missing, picked, selected = renamed
                if not missing:
                    self._say_nothing()
                    return
                continue
            done = None
            if key == aiplan_screen.KEY:
                # About the picked ones, or with none picked, all of them: the AI picks (and it's told
                # where the selection is)
                done = self._ask_ai(chosen.files or only_missing,
                                    chosen.files or (contextmenu.under(only_missing, selected) if selected else []))
            elif key == picker.SIDE_KEY:
                done = self._act_in_dst(chosen.side_selected, chosen.side_pressed == self.SIDE_REMOVE_KEY)
            elif not key:
                done = self._act(chosen.files, selected)
                if done is filescreen.READ_ANEW:
                    key = self.REFRESH_KEY
            if key == self.REFRESH_KEY:
                done = []
                self._read_anew_replicas(to_refresh)
                is_changed = self.has_changed
            else:
                if done is None:
                    picked = chosen.files
                    continue
                is_changed = bool(done) and not dryrun.DRYRUN
                self.has_changed = self.has_changed or is_changed
            missing = self._missing_after(missing, done, is_changed)
            if not missing:
                self._say_nothing()
                return
            still_missing = set(missing)
            done = set(done)
            picked = [relpath for relpath in chosen.files if relpath in still_missing and relpath not in done]
            selected = filescreen.shown_near(selected, missing, shown_before)

    def _after_rename(self, chosen, selected):
        """Rename the selected file or dir (cc), as chosen says; returns None if it wasn't, else
        (what's missing now, what's picked of it, where to select)"""
        renamed = self._rename_selected(selected)
        if renamed is None:
            return None
        new_relpath, moves = renamed
        missing = self._listed()
        moved = dict(moves)
        still_missing = set(missing)
        picked = [moved.get(relpath, relpath) for relpath in chosen.files
                  if moved.get(relpath, relpath) in still_missing]
        return missing, picked, filescreen.shown_near(new_relpath, missing) if missing else None

    def _read_anew_replicas(self, to_refresh):
        """Read anew each of to_refresh ([(replica, the relpath whose folder is read, on Drive)]),
        forgetting what was found of it"""
        if any(replica is self._dst for replica, _ in to_refresh):
            self._side_listing.invalidate()
        for replica, relpath in to_refresh:
            if replica_ops.read_anew(replica, relpath):
                self.has_changed = self.was_read_anew = True
                self._index_of(replica).invalidate()
                # Its files may have other contents now
                self.checked.clear()
                for job in hashes_screen.jobs_of([replica]):
                    if replica is self._dst:
                        hashes_screen.scan_with_listing(job, self._side_listing)
                    else:
                        job.scan_in_background()

    def _missing_after(self, missing, done, is_changed):
        """What's missing after an action that did done (relpaths), if it changed anything"""
        if is_changed and self._last_action in (self.COPY, self.COPY_BACK, self.REMOVE):
            # Only the ones done aren't missing now (copied to dst, or removed from src), or
            # differ (copied either way): no need to diff the replicas anew, which for local
            # ones scans them both
            done_now = set(done)
            missing = [relpath for relpath in missing if relpath not in done_now]
            for relpath in done_now:
                self.differs.pop(relpath, None)
        elif is_changed:
            # Diffed anew (the trees as they are now: no background finding)
            self._missing_future = self._differs_future = None
            missing = self._listed()
        return missing
