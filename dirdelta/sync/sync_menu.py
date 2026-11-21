"""The sync menu of a pair of replicas (SyncMenu): each way's files, the files that differ, reading
the replicas anew, hashing the local ones' files (all, or all but the media files), the dashboard (the terminal's: the browser's is its Replicas tab) and favorites"""
import concurrent.futures
import datetime

from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashing
from dirdelta.screens.hashes_screen import status as hash_status
from dirdelta.known import replicainfo
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.matching import elsewhere
from dirdelta.matching import syncstate
from dirdelta.screens import hashes_screen
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync import combined
from dirdelta.sync import view
from dirdelta.sync import viewing
from dirdelta.sync.options import STATE, STATE_POINTS, SYNC_ALL, Action, state_lines, sync_all_shown_as
from dirdelta.sync.ways import DIFFER, Way, find_all, find_differing
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import frontend
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.known import mounts
from dirdelta.util import dryrun

# The sync menu's last option: it doesn't quit dirdelta, the start menu shows again (as with q)
BACK = "End the sync"
# The menu's sections' headings (in grey, skipped when moving), as the start menu's: the sync of all
# the differences, a kind of them at a time, what makes the comparison up to date, and the pair's
# own things
SYNC_SECTION = '\u2500\u2500 Sync \u2500\u2500'
UPDATE_SECTION = '\u2500\u2500 Bring the comparison up to date \u2500\u2500'
PAIR_SECTION = '\u2500\u2500 This pair \u2500\u2500'


class SyncMenu(viewing.Viewing):
    """The main menu of a sync of replica_a and replica_b (at their paths), until the user goes back.
    With known_replicas (a Replicas, saved when changed), it also makes the pair a favorite, or not.
    changes: where the files changed live are noted (a log_entries.Changes), if anywhere."""
    ADD_FAVORITE = "Add to favorites"
    REMOVE_FAVORITE = "Remove from favorites"
    DASHBOARD = hashes_screen.TITLE

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
        self.action_labels = {}
        for way, src_path, dst_path, scope in ((self.ways[0], self.replica_a_path, self.replica_b_path, view.ONLY_A),
                                               (self.ways[1], self.replica_b_path, self.replica_a_path, view.ONLY_B)):
            label = "Files only in %s" % (src_path,)
            self.actions[label] = Action(src_path, dst_path, way, self.changes)
            self.action_labels[scope] = label
        self.action_labels[view.DIFFER] = DIFFER
        # The files both have that differ (differing.py), alone, a's way (Copy replaces b's, Copy back a's)
        self.actions[DIFFER] = Action(self.replica_a_path, self.replica_b_path, self.ways[0], self.changes, only_differing=True)
        # A cloud replica's folder can be read anew from Drive, if Drive changed since the cache was made
        # (each by its short name, as the combined tree says it)
        names = replicanames.short_names([self.replica_a_path, self.replica_b_path])
        # (The web version's pages show them by these names, each in its color, on every screen of the sync)
        frontend.show_replicas([(self.replica_a_path, names[self.replica_a_path]), (self.replica_b_path, names[self.replica_b_path])])
        self.refreshes = {"Refresh %s's file list from Google Drive" % (names[path],): replica
                          for replica, path in ((self.replica_a, self.replica_a_path), (self.replica_b, self.replica_b_path))
                          if isinstance(replica, clouddirtree.CloudDirTree)}
        # A local one can be scanned anew, if its files changed meanwhile, outside dirdelta
        self.rescans = {"Rescan %s" % (names[path],): replica
                        for replica, path in ((self.replica_a, self.replica_a_path), (self.replica_b, self.replica_b_path))
                        if localdiskdirtree.is_local(replica)}
        # The files of the same size compared on request (see comparing.py), a's way
        self.compared = {}
        for way in self.ways:
            way.compared = self.compared
        self.jobs = hashes_screen.jobs_of([self.replica_a, self.replica_b])
        # When to find the files that differ again, as the replicas' files are hashed
        self.as_hashed = comparing.AsHashed(self.jobs)
        self._find_all()
        # What each way found last, noted in known_replicas (once each time they're found)
        self.noted = []
        # The combined tree's marks, kept while the user goes back to the menu and comes back to it (until
        # they're done: the files are other ones then)
        self.combined_chosen = {}

    def run(self):
        """Show the menu until the user goes back (returns None)"""
        while True:
            favorite_options = []
            if self.known_replicas is not None:
                is_favorite = self.known_replicas.is_favorite(self.replica_a_path, self.replica_b_path)
                favorite_options = [self.REMOVE_FAVORITE if is_favorite else self.ADD_FAVORITE]
            options = picker.grouped([
                [picker.Option(line, line, picker.Skipped(line)) for line in (STATE,) + STATE_POINTS],
                # (One entry: which files, and how they're chosen, are chosen in it: view.py)
                [picker.Skipped(SYNC_SECTION), SYNC_ALL],
                [picker.Skipped(UPDATE_SECTION), comparing.COMPARE] + list(self.rescans) + list(self.refreshes) +
                ([hashes_screen.CHOOSE_TITLE] if self.jobs else []),
                # (In the browser the Replicas tab is the dashboard, where they're named too)
                [picker.Skipped(PAIR_SECTION)] + ([self.DASHBOARD] if frontend.current is None else []) + favorite_options,
                [BACK]])
            option = picker.pick_option(options,
                                        shown_as=self.shown_as, selected=SYNC_ALL,
                                        help_lines=["The sync state's mark:"] +
                                        ["  " + line for line in syncstate.help_lines()])
            self.note_compared()
            if option in (None, BACK):
                # Back to the start menu (q too)
                return None
            if option == hashes_screen.CHOOSE_TITLE:
                hashes_screen.choose(self.jobs)
                continue
            if option == self.DASHBOARD:
                hashes_screen.dashboard([self.replica_a, self.replica_b], self.known_replicas)
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
        if option == comparing.COMPARE:
            changes = self.ways[0].differs.result()
            if changes.uncompared:
                comparing.compare(changes.uncompared, self.replica_a, self.replica_b, self.indexes[self.replica_a],
                                  self.indexes[self.replica_b], self.compared)
                self._find_differing()
            return
        if option in self.rescans:
            if replica_ops.rescan_replica(self.rescans[option]):
                self.indexes[self.rescans[option]].invalidate()
                for way in self.ways:
                    # Its files may have other contents now
                    way.checked.clear()
                self.compared.clear()
                self._find_all()
                for job in hashes_screen.jobs_of([self.rescans[option]]):
                    job.scan_in_background()
            return
        if option in self.refreshes:
            if replica_ops.refresh_replica(self.refreshes[option]):
                self.indexes[self.refreshes[option]].invalidate()
                for way in self.ways:
                    # Its files may have other contents now
                    way.checked.clear()
                self.compared.clear()
                self._find_all()
            return
        if option == SYNC_ALL:
            # Its differences in one screen, in the view chosen there (viewing.py), until the user goes back
            self.sync_view()
            return
        # (One side's files tree, by its label: opened by its view, ACT, in the sync's screen; not offered in the menu)
        scope = next((scope for scope, label in self.action_labels.items() if label == option), None)
        if scope is not None:
            self.sync_view(scope, view.ACT)

    def _still_differ(self):
        """Whether the replicas still differ, once each way's found again (False if that failed)"""
        try:
            missing = [way.missing.result() for way in self.ways]
            return any(found.relpaths for found in missing) or bool(self.ways[0].differs.result())
        except Exception:
            return False

    def _find_all(self):
        """Start finding (again) what each way lacks, and the files that differ"""
        self.as_hashed.found()
        find_all(self.ways, self.compared)

    def _find_differing(self):
        """Start finding (again) the files that differ"""
        self.as_hashed.found()
        find_differing(self.ways, self.compared)

    def note_compared(self):
        """Note what each way found last in known_replicas (once each time they're found)"""
        futures = [way.missing for way in self.ways]
        if self.known_replicas is None or futures == self.noted or not all(
                future.done() and future.exception() is None for future in futures):
            return
        self.noted[:] = futures
        self.known_replicas.note_compared(self.replica_a_path, self.replica_b_path,
                                          *[len(future.result().relpaths) for future in futures],
                                          when=datetime.datetime.now(), totals=self._totals())
        replicas.save(self.known_replicas)

    def _totals(self):
        """[how many files each replica has], or None if one's isn't known: a local replica has no tree of
        them (dirdiff lists them), so its hashing job's listing says"""
        totals = []
        for replica in (self.replica_a, self.replica_b):
            if localdiskdirtree.is_local(replica):
                job = hashing.job_for(replica.fullpath())
                progress = job.progress() if job is not None else None
                if progress is None or progress.state in (hashing.NOT_SCANNED, hashing.SCANNING):
                    return None
                totals.append(progress.nr_files + progress.nr_left_out)
            else:
                totals.append(sum(1 for _ in replica.iter_files()))
        return totals

    def shown_as(self):
        """The menu's options as they're shown now: each way's count, the state line, the
        dashboard's and the refreshes' notes"""
        if self.as_hashed.is_due(self.ways[0].differs):
            self._find_differing()
        # (What each way found, noted as soon as it's found, not only once the user picks an option: one leaving the
        # menu first left the pair's status as it was before)
        try:
            self.note_compared()
        except replicas.ReplicasError:
            pass
        shown = {label: action.shown_as() for label, action in self.actions.items()}
        shown[SYNC_ALL] = sync_all_shown_as(self.ways, self.replica_a_path, self.replica_b_path)
        shown[comparing.COMPARE] = comparing.shown_as(self.ways[0].differs)
        # Only to read: moving goes past them
        shown.update(state_lines(self.ways, self.replica_a_path, self.replica_b_path))
        shown[self.DASHBOARD] = "%s: files, last updates, hashes%s" % (
            self.DASHBOARD, " (%s)" % ("; ".join(text for text, _ in hash_status.status_parts(self.jobs)),) if self.jobs else "")
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
