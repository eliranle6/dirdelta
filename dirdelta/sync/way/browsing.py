"""The sync's file picker: the loop that shows it and does what's chosen"""
import functools
import os

from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashing
from dirdelta.known import replicanames
from dirdelta.matching import differing
from dirdelta.matching import elsewhere
from dirdelta.screens import aiplan_screen
from dirdelta.screens import archive_screen
from dirdelta.screens import hashes_screen
from dirdelta.sync import replica_ops
from dirdelta.ui import contextmenu
from dirdelta.ui import filescreen
from dirdelta.ui import images
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.ui import renaming
from dirdelta.util import dryrun


class Browsing(object):
    """The picker, shown until it's quit (InteractiveDirSync's)"""

    def _browse(self):
        """Let the user pick some of the files of src that dst lacks, then choose what to do with
        them (_act()): after that, or after choosing nothing, pick again, where they were, with the
        files done no longer there (or, in a dry run, no longer picked), until they quit."""
        missing = self._listed()
        if not missing:
            self._say_nothing()
            return
        clouds = [replica for replica in (self._src, self._dst)
                  if isinstance(replica, clouddirtree.CloudDirTree)]
        jobs = hashes_screen.jobs_of([self._src, self._dst])
        src_name, dst_name = (replicanames.full(replica.displayname() if not replica_ops.is_local(replica) else replica.fullpath())
                              for replica in (self._src, self._dst))
        header = ("%s has other versions of these. Pick some, then choose what to do with them." % (dst_name,)
                  if self._only_differing else
                  "%s lacks these. Pick some, then choose what to do with them." % (dst_name,))
        keys = self.REFRESH_KEY + hashes_screen.KEY + aiplan_screen.KEY + contextmenu.KEY + archive_screen.KEY
        # The keys row has little room: the rest are in the menu (:), and ?
        key_hints = [('Enter', 'choose what to do'), contextmenu.KEY_HINT]
        more_keys = ([aiplan_screen.KEY_HINT, archive_screen.KEY_HINT, opening.KEY_HINT, renaming.KEY_HINT,
                      ('Ctrl-W l', 'move to %s, on the right (Ctrl-W h: back)' % (dst_name,)),
                      (self.SIDE_REMOVE_KEY + ' there', 'remove what\'s selected there'),
                      ('Enter, : there', 'choose what to do with it')] +
                     [(self.REFRESH_KEY_NAME, 'read the folder anew from Drive' if clouds else 'see what changed outside dirdelta'),
                      hashes_screen.KEY_HINT])
        picked, selected = [], None
        # Where to go on in the side tree, after what was done there
        side_start = None
        while True:
            src_job = hashing.job_for(self._src.fullpath()) if replica_ops.is_local(self._src) else None
            if src_job is not None:
                # The files shown first: they're the ones to compare
                src_job.first(missing)
            marks = hashes_screen.Marks(src_job, missing, jobs, extra=self._opener.status_parts) if jobs else None
            files = set(missing)
            shown_before = missing

            # The files that differ, whose tags are sent once (then with what's sent of them again)
            differs = dict(self.differs)
            untagged = set(differs)

            def shown_as(marks=marks, src_job=src_job, differs=differs, untagged=untagged):
                """The hashing tags (Marks), the downloads' to open the files (opening.py), and the
                files that differ's (differing.py)"""
                shown = marks() if marks is not None else {'': picker.segments(self._opener.status_parts())}

                def name_of(relpath):
                    return marks.text(relpath) if marks is not None else os.path.basename(relpath)
                shown = opening.with_tags(shown, self._opener, name_of)
                for relpath in untagged | (set(shown) & set(differs)):
                    shown[relpath] = (shown.get(relpath) or name_of(relpath)) + differing.styled_tag(differs[relpath])
                untagged.clear()
                return shown
            only_missing = [relpath for relpath in missing if relpath not in differs]
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
                    previews=functools.partial(self._find_previews, only_missing, differs),
                    on_selection=functools.partial(elsewhere.check_contents, only_missing, self._src,
                                                   self.src_index, self.dst_index, self.checked),
                    # A photo's picture below that
                    images=images.of_replica(self._src))
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
            # Ctrl-R there reads dst anew (on Drive, what's selected there); here, what's on Drive (what's
            # selected here), and only without any on Drive, the local ones
            to_refresh = [(replica, selected) for replica in clouds or (self._src, self._dst)]
            if key == picker.SIDE_KEY and chosen.side_pressed == self.REFRESH_KEY:
                key = self.REFRESH_KEY
                to_refresh = [(self._dst, chosen.side_selected)]
            if key == renaming.PRESSED:
                picked = chosen.files
                renamed = self._rename_selected(selected)
                if renamed is None:
                    continue
                new_relpath, moves = renamed
                missing = self._listed()
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
                if any(replica is self._dst for replica, _ in to_refresh):
                    self._side_listing.invalidate()
                for replica, relpath in to_refresh:
                    if replica_ops._read_anew(replica, relpath):
                        self.has_changed = self.was_read_anew = True
                        self._index_of(replica).invalidate()
                        # Its files may have other contents now
                        self.checked.clear()
                        for job in hashes_screen.jobs_of([replica]):
                            if replica is self._dst:
                                hashes_screen.scan_with_listing(job, self._side_listing)
                            else:
                                job.scan_in_background()
                is_changed = self.has_changed
            else:
                if done is None:
                    picked = chosen.files
                    continue
                is_changed = bool(done) and not dryrun.DRYRUN
                self.has_changed = self.has_changed or is_changed
            if is_changed and self._last_action in (self.COPY, self.COPY_BACK, self.REMOVE):
                # Only the ones done aren't missing now (copied to dst, or removed from src), or
                # differ (copied either way): no need to diff the replicas anew, which for local
                # ones scans them both
                done_now = set(done)
                missing = [relpath for relpath in missing if relpath not in done_now]
                for relpath in done_now:
                    self.differs.pop(relpath, None)
                if not missing:
                    self._say_nothing()
                    return
            elif is_changed:
                # Diffed anew (the trees as they are now: no background finding)
                self._missing_future = self._differs_future = None
                missing = self._listed()
                if not missing:
                    self._say_nothing()
                    return
            still_missing = set(missing)
            done = set(done)
            picked = [relpath for relpath in chosen.files if relpath in still_missing and relpath not in done]
            selected = filescreen.shown_near(selected, missing, shown_before)
