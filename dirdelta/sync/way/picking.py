"""What the sync's file picker is shown with, and showing it once"""
import functools
import os
import types

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


class Picking(object):
    """The picker (InteractiveDirSync's)"""

    def _picker_screen(self):
        """What the picker is shown with each time: the replicas on Drive, the hashing jobs, the
        replicas' names, its header, its keys and their hints"""
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
        return types.SimpleNamespace(clouds=clouds, jobs=jobs, src_name=src_name, dst_name=dst_name, header=header,
                                     keys=keys, key_hints=key_hints, more_keys=more_keys)

    def _pick(self, screen, missing, picked, selected, side_start):
        """Show the picker of missing (screen: _picker_screen()'s), with picked picked, on selected
        (and in the side tree, on side_start, if it's not None). Returns (what was chosen, a
        picker.Picked or None if it was quit, the missing files that don't differ)"""
        src_job = hashing.job_for(self._src.fullpath()) if replica_ops.is_local(self._src) else None
        if src_job is not None:
            # The files shown first: they're the ones to compare
            src_job.first(missing)
        marks = hashes_screen.Marks(src_job, missing, screen.jobs, extra=self._opener.status_parts) if screen.jobs else None
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
                screen.src_name, missing, header=screen.header, picked=picked,
                keys=screen.keys, selected=selected, key_hints=screen.key_hints,
                shown_as=shown_as, notify_keys=opening.KEY, twice_keys=renaming.KEY,
                # dst beside it, to look through (e.g. for a newer version of a file)
                side=picker.Side(screen.dst_name, self._side_items(), True, self._side_follow,
                                 self.SIDE_REMOVE_KEY + contextmenu.KEY + self.REFRESH_KEY,
                                 [('Enter', 'choose what to do'), (self.SIDE_REMOVE_KEY, 'remove'), contextmenu.KEY_HINT,
                                  (self.REFRESH_KEY_NAME, filescreen.SIDE_REFRESH_HINTS[self._dst in screen.clouds])],
                                 side_start),
                enter_picks_selection=True,
                none_picked_key_hints=[('Enter', 'Pick & choose what to do')],
                # Ctrl-X opens the selected one (the picked ones: the menu's Open)
                on_notify=lambda key, selected, picked: self._opener.press([selected], files),
                help_lines=picker.key_help_lines(screen.more_keys) + (hashes_screen.HELP_LINES if screen.jobs else []),
                previews=functools.partial(self._find_previews, only_missing, differs),
                on_selection=functools.partial(elsewhere.check_contents, only_missing, self._src,
                                               self.src_index, self.dst_index, self.checked),
                # A photo's picture below that
                images=images.of_replica(self._src))
        finally:
            if marks is not None:
                marks.close()
        return chosen, only_missing
