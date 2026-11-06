"""The sync menu of a pair of replicas (SyncMenu): each way's files, the files that differ, reading
the replicas anew, the dashboard, labels and favorites"""
import concurrent.futures
import datetime

from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashing
from dirdelta.known import replicainfo
from dirdelta.known import replicas
from dirdelta.matching import elsewhere
from dirdelta.matching import syncstate
from dirdelta.screens import hashes_screen
from dirdelta.screens import label_screen
from dirdelta.sync import replica_ops
from dirdelta.sync.options import STATE, Action, state_line
from dirdelta.sync.ways import DIFFER, Way, find_all
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.known import mounts
from dirdelta.util import dryrun

# The sync menu's last option: it doesn't quit dirdelta, the start menu shows again (as with q)
BACK = "Back to the start menu"


class SyncMenu(object):
    """The main menu of a sync of replica_a and replica_b (at their paths), until the user goes back.
    With known_replicas (a Replicas, saved when changed), it also makes the pair a favorite, or not.
    changes: where the files changed live are noted (a log_entries.Changes), if anywhere."""
    ADD_FAVORITE = "Add to favorites"
    REMOVE_FAVORITE = "Remove from favorites"
    DASHBOARD = hashes_screen.TITLE
    LABELS = "Label the replicas"

    def __init__(self, replica_a, replica_b, replica_a_path, replica_b_path, known_replicas=None, changes=None):
        self.replica_a, self.replica_b = replica_a, replica_b
        self.replica_a_path, self.replica_b_path = replica_a_path, replica_b_path
        self.known_replicas, self.changes = known_replicas, changes
        read_only = (_read_only_lines(self.replica_a, self.replica_a_path) +
                     _read_only_lines(self.replica_b, self.replica_b_path))
        if read_only:
            messages.show("Read-only", read_only, dryrun.label(), 'yellow')
        # Each way, the files in one replica that aren't in the other, to pick and then copy, remove or
        # rename (interactive_dir_sync): found once, in the background, with each option saying how
        # many there are once they are. Each replica's files by name (for finding where the other has a
        # file of a name) are kept, so they're listed once.
        self.indexes = {replica: elsewhere.Index(replica) for replica in (self.replica_a, self.replica_b)}
        self.ways = [Way(self.replica_a, self.replica_b, self.indexes), Way(self.replica_b, self.replica_a, self.indexes)]
        self.actions = {}
        for way, src_path, dst_path in ((self.ways[0], self.replica_a_path, self.replica_b_path),
                                        (self.ways[1], self.replica_b_path, self.replica_a_path)):
            label = "Files only in %s" % (src_path,)
            self.actions[label] = Action(src_path, dst_path, way, self.changes)
        # The files both have that differ (differing.py), alone, a's way (Copy replaces b's, Copy back a's)
        self.actions[DIFFER] = Action(self.replica_a_path, self.replica_b_path, self.ways[0], self.changes, only_differing=True)
        # A cloud replica's folder can be read anew from Drive, if Drive changed since the cache was made
        self.refreshes = {"Refresh %s file list from Google Drive" % (path,): replica
                          for replica, path in ((self.replica_a, self.replica_a_path), (self.replica_b, self.replica_b_path))
                          if isinstance(replica, clouddirtree.CloudDirTree)}
        # A local one can be scanned anew, if its files changed meanwhile, outside dirdelta
        self.rescans = {"Rescan %s" % (path,): replica
                             for replica, path in ((self.replica_a, self.replica_a_path), (self.replica_b, self.replica_b_path))
                        if localdiskdirtree.is_local(replica)}
        find_all(self.ways)
        self.jobs = hashes_screen.jobs_of([self.replica_a, self.replica_b])
        # What each way found last, noted in known_replicas (once each time they're found)
        self.noted = []

    def run(self):
        """Show the menu until the user goes back (returns None)"""
        while True:
            favorite_options = []
            if self.known_replicas is not None:
                is_favorite = self.known_replicas.is_favorite(self.replica_a_path, self.replica_b_path)
                favorite_options = [self.REMOVE_FAVORITE if is_favorite else self.ADD_FAVORITE]
            options = ([picker.Option(STATE, STATE, picker.Skipped(STATE)), picker.BLANK] + list(self.actions) +
                       list(self.rescans) + list(self.refreshes) + [self.DASHBOARD] + favorite_options +
                       ([self.LABELS] if self.known_replicas is not None else []) + [BACK])
            option = picker.pick_option(options,
                                        shown_as=self.shown_as, selected=list(self.actions)[0],
                                        help_lines=syncstate.help_lines())
            self.note_compared()
            if option in (None, BACK):
                # Back to the start menu (q too)
                return None
            if option == self.DASHBOARD:
                hashes_screen.dashboard([self.replica_a, self.replica_b], self.known_replicas)
                continue
            if option == self.LABELS:
                label_screen.run(self.known_replicas, [self.replica_a_path, self.replica_b_path])
                continue
            if option in (self.ADD_FAVORITE, self.REMOVE_FAVORITE):
                self.known_replicas.toggle_favorite(self.replica_a_path, self.replica_b_path)
                replicas.save(self.known_replicas)
                continue
            self._do(option)

    def _do(self, option):
        """Do what option of the menu (one of a way, a rescan's or a refresh's) says"""
        # An action may change the trees (or dirs) that the other way may still be diffing, so
        # both are waited for
        if not all(way.missing.done() and way.differs.done() for way in self.ways):
            messages.print_line("Finding the files that each lacks...")
        concurrent.futures.wait([way.missing for way in self.ways] + [way.differs for way in self.ways])
        if option in self.rescans:
            if replica_ops.rescan_replica(self.rescans[option]):
                self.indexes[self.rescans[option]].invalidate()
                for way in self.ways:
                    # Its files may have other contents now
                    way.checked.clear()
                find_all(self.ways)
                for job in hashes_screen.jobs_of([self.rescans[option]]):
                    job.scan_in_background()
            return
        if option in self.refreshes:
            if replica_ops.refresh_replica(self.refreshes[option]):
                self.indexes[self.refreshes[option]].invalidate()
                for way in self.ways:
                    # Its files may have other contents now
                    way.checked.clear()
                find_all(self.ways)
            return
        # Copying, removing and renaming change the files (unless it's a dry run), and so what each
        # lacks, and so does reading a replica anew from Drive (in the file picker)
        if self.actions[option].run():
            for way in self.ways:
                # The way shown cleared its own; its files may have other contents for this one too
                if self.actions[option].was_read_anew:
                    way.checked.clear()
            find_all(self.ways)
            # Files copied into a local replica (or moved in it) are hashed too
            for job in self.jobs:
                job.scan_in_background()

    def note_compared(self):
        """Note what each way found last in known_replicas (once each time they're found)"""
        futures = [way.missing for way in self.ways]
        if self.known_replicas is None or futures == self.noted or not all(
                future.done() and future.exception() is None for future in futures):
            return
        self.noted[:] = futures
        self.known_replicas.note_compared(self.replica_a_path, self.replica_b_path,
                                          *[len(future.result().relpaths) for future in futures],
                                          when=datetime.datetime.now())
        replicas.save(self.known_replicas)

    def shown_as(self):
        """The menu's options as they're shown now: each way's count, the state line, the
        dashboard's and the refreshes' notes"""
        shown = {label: action.shown_as() for label, action in self.actions.items()}
        # Only to read: moving goes past them
        shown[STATE] = state_line(self.ways, self.replica_a_path, self.replica_b_path)
        shown[self.DASHBOARD] = "%s: files, last updates, hashes%s" % (
            self.DASHBOARD, " (%s)" % ("; ".join(text for text, _ in hashing.status_parts(self.jobs)),) if self.jobs else "")
        if self.jobs:
            shown[''] = hashes_screen.picker_status([self.replica_a, self.replica_b])
        # When Drive's file list was read, in its freshness's color (today, this week, before)
        for label in self.refreshes:
            read = replicainfo.cache_time(self.refreshes[label].displayname())
            shown[label] = picker.styled([(label + " ", None), (
                "(%s list read %s)" % (replicainfo.CACHE_MARK, read.strftime('%d.%m.%Y %H:%M')) if read else "",
                replicainfo.freshness(read))])
        return shown


def _read_only_lines(replica, replica_path):
    """What can't be done with the replica, and what can, if it's read-only"""
    if not replica_ops.is_writable(replica):
        return ["%s is read-only (no write permission): you can still copy its files to the other replica, "
                "but dirdelta won't copy files into it, remove files from it or move them in it." % (replica_path,)
                ] + mounts.read_only_lines_of(replica_path)
    return []
