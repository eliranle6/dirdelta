import concurrent.futures
import datetime
import threading
import time

from dirdelta.drive import clouddirtree
from dirdelta.matching import differing
from dirdelta.drive import drivemeta
from dirdelta.util import dryrun
from dirdelta.matching import elsewhere
from dirdelta.hashes import hashcache
from dirdelta.screens import hashes_screen
from dirdelta.hashes import hashing
from dirdelta.sync import interactive_dir_sync
from dirdelta.screens import label_screen
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from dirdelta.known import mounts
from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.known import replicainfo
from dirdelta.known import replicalog
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.matching import syncstate
from dirdelta.trees import replicafactory
from dirdelta.util import text
from dirdelta.sync import replica_ops


# The sync menu's last option: it doesn't quit dirdelta, the start menu shows again (as with q)
BACK = "Back to the start menu"


def run(args):
    """Sync the replicas at args' paths, until the user goes back (to the start menu)"""
    names = replicanames.short_names([args.dir_a_path, args.dir_b_path])
    with picker.place("Sync %s \u21c4 %s" % (names[args.dir_a_path], names[args.dir_b_path])):
        return _run(args)


def _run(args):
    if not paths.is_cloud_path(args.dir_a_path) and not paths.is_cloud_path(args.dir_b_path):
        # Two local dirs: each action diffs them with dirdiff, which scans them anew, so there's
        # nothing to scan here
        for path in (args.dir_a_path, args.dir_b_path):
            replicafactory.validate_dir(path)
        dirtree_a = localdiskdirtree.LocalReplica(args.dir_a_path, True, args.max_depth)
        dirtree_b = localdiskdirtree.LocalReplica(args.dir_b_path, True, args.max_depth)
    else:
        dirtree_a = replicafactory.create_dirtree_from_arg(args.dir_a_path, args.max_depth)
        if dirtree_a is None:
            return
        dirtree_b = replicafactory.create_dirtree_from_arg(args.dir_b_path, args.max_depth)
        if dirtree_b is None:
            return
        warnings = replica_ops.scan_errors_warning(dirtree_a) + replica_ops.scan_errors_warning(dirtree_b)
        if warnings:
            messages.show("Warning: couldn't read everything", warnings, dryrun.label(), 'red')
    # Both are dirs (or Drive's), so they're the history's latest; and what's known of each (its
    # log's last entry, see replicalog.py) is as it is now
    known_replicas = replicas.load()
    known_replicas.record(args.dir_a_path, args.dir_b_path)
    trees = [(dirtree_a, args.dir_a_path), (dirtree_b, args.dir_b_path)]
    replicalog.note_seen(trees, known_replicas)
    replicas.save(known_replicas)
    # The local replicas' files' hashes, which find a file by its contents: hashed in the
    # background, if the user wants, and kept in each (see hashcache.use_replica())
    for tree in (dirtree_a, dirtree_b):
        if localdiskdirtree.is_local(tree):
            hashcache.use_replica(tree.fullpath())
    if not hashes_screen.offer(hashes_screen.prepare([dirtree_a, dirtree_b])):
        return
    changes = replicalog.Changes()
    # A Drive replica's file list is kept in it too, as it changes (see drivemeta.py)
    with drivemeta.kept([(args.dir_a_path, dirtree_a), (args.dir_b_path, dirtree_b)]):
        result = _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path, known_replicas, changes)
    replicalog.offer_entries(changes, trees, known_replicas)
    return result


def _sync(replica_a, replica_b, replica_a_path, replica_b_path, known_replicas=None, changes=None):
    """The main menu, until the user quits. With known_replicas (a Replicas, saved when changed),
    it also makes the pair a favorite, or not. changes: where the files changed live are noted (a
    replicalog.Changes), if anywhere."""
    ADD_FAVORITE = "Add to favorites"
    REMOVE_FAVORITE = "Remove from favorites"
    DASHBOARD = hashes_screen.TITLE
    LABELS = "Label the replicas"
    read_only = _read_only_lines(replica_a, replica_a_path) + _read_only_lines(replica_b, replica_b_path)
    if read_only:
        messages.show("Read-only", read_only, dryrun.label(), 'yellow')
    # Each way, the files in one replica that aren't in the other, to pick and then copy, remove or
    # rename (interactive_dir_sync): found once, in the background, with each option saying how
    # many there are once they are. Each replica's files by name (for finding where the other has a
    # file of a name) are kept, so they're listed once.
    indexes = {replica: elsewhere.Index(replica) for replica in (replica_a, replica_b)}
    ways = [_Way(replica_a, replica_b, indexes), _Way(replica_b, replica_a, indexes)]
    actions = {}
    for way, src_path, dst_path in ((ways[0], replica_a_path, replica_b_path),
                                    (ways[1], replica_b_path, replica_a_path)):
        label = "Files only in %s" % (src_path,)
        actions[label] = _Action(src_path, dst_path, way, changes)
    # The files both have that differ (differing.py), alone, a's way (Copy replaces b's, Copy back a's)
    actions[DIFFER] = _Action(replica_a_path, replica_b_path, ways[0], changes, only_differing=True)
    # A cloud replica's folder can be read anew from Drive, if Drive changed since the cache was made
    refreshes = {"Refresh %s file list from Google Drive" % (path,): replica
                 for replica, path in ((replica_a, replica_a_path), (replica_b, replica_b_path))
                 if isinstance(replica, clouddirtree.CloudDirTree)}
    # A local one can be scanned anew, if its files changed meanwhile, outside dirdelta
    rescans = {"Rescan %s" % (path,): replica for replica, path in ((replica_a, replica_a_path), (replica_b, replica_b_path))
               if localdiskdirtree.is_local(replica)}
    _find_all(ways)
    jobs = hashes_screen.jobs_of([replica_a, replica_b])
    # What each way found last, noted in known_replicas (once each time they're found)
    noted = []

    def note_compared():
        futures = [way.missing for way in ways]
        if known_replicas is None or futures == noted or not all(
                future.done() and future.exception() is None for future in futures):
            return
        noted[:] = futures
        known_replicas.note_compared(replica_a_path, replica_b_path, *[len(future.result().relpaths) for future in futures],
                                     when=datetime.datetime.now())
        replicas.save(known_replicas)

    def shown_as():
        shown = {label: action.shown_as() for label, action in actions.items()}
        # Only to read: moving goes past them
        shown[STATE] = _state_line(ways, replica_a_path, replica_b_path)
        shown[DASHBOARD] = "%s: files, last updates, hashes%s" % (
            DASHBOARD, " (%s)" % ("; ".join(text for text, _ in hashing.status_parts(jobs)),) if jobs else "")
        if jobs:
            shown[''] = hashes_screen.picker_status([replica_a, replica_b])
        # When Drive's file list was read, in its freshness's color (today, this week, before)
        for label in refreshes:
            read = replicainfo.cache_time(refreshes[label].displayname())
            shown[label] = picker.styled([(label + " ", None), (
                "(%s list read %s)" % (replicainfo.CACHE_MARK, read.strftime('%d.%m.%Y %H:%M')) if read else "",
                replicainfo.freshness(read))])
        return shown

    # Present sync options until user quits
    while True:
        favorite_options = []
        if known_replicas is not None:
            is_favorite = known_replicas.is_favorite(replica_a_path, replica_b_path)
            favorite_options = [REMOVE_FAVORITE if is_favorite else ADD_FAVORITE]
        option = picker.pick_option([picker.Option(STATE, STATE, picker.Skipped(STATE)), picker.BLANK] + list(actions) + list(rescans) + list(refreshes) + [DASHBOARD] +
                                    favorite_options + ([LABELS] if known_replicas is not None else []) + [BACK],
                                    shown_as=shown_as, selected=list(actions)[0],
                                    help_lines=syncstate.help_lines())
        note_compared()
        if option in (None, BACK):
            # Back to the start menu (q too)
            return None
        if option == DASHBOARD:
            hashes_screen.dashboard([replica_a, replica_b], known_replicas)
            continue
        if option == LABELS:
            label_screen.run(known_replicas, [replica_a_path, replica_b_path])
            continue
        if option in (ADD_FAVORITE, REMOVE_FAVORITE):
            known_replicas.toggle_favorite(replica_a_path, replica_b_path)
            replicas.save(known_replicas)
            continue
        # An action may change the trees (or dirs) that the other way may still be diffing, so
        # both are waited for
        if not all(way.missing.done() and way.differs.done() for way in ways):
            messages.print_line("Finding the files that each lacks...")
        concurrent.futures.wait([way.missing for way in ways] + [way.differs for way in ways])
        if option in rescans:
            if replica_ops.rescan_replica(rescans[option]):
                indexes[rescans[option]].invalidate()
                for way in ways:
                    # Its files may have other contents now
                    way.checked.clear()
                _find_all(ways)
                for job in hashes_screen.jobs_of([rescans[option]]):
                    job.scan_in_background()
            continue
        if option in refreshes:
            if replica_ops.refresh_replica(refreshes[option]):
                indexes[refreshes[option]].invalidate()
                for way in ways:
                    # Its files may have other contents now
                    way.checked.clear()
                _find_all(ways)
            continue
        # Copying, removing and renaming change the files (unless it's a dry run), and so what each
        # lacks, and so does reading a replica anew from Drive (in the file picker)
        if actions[option].run():
            for way in ways:
                # The way shown cleared its own; its files may have other contents for this one too
                if actions[option].was_read_anew:
                    way.checked.clear()
            _find_all(ways)
            # Files copied into a local replica (or moved in it) are hashed too
            for job in jobs:
                job.scan_in_background()


_files = text.files

# The sync menu's option of the files both replicas have that differ
DIFFER = "Files that differ"


def _differ(count):
    return "differs" if count == 1 else "differ"


def _find_all(ways):
    """Start finding (again) what each way lacks, and the files both have that differ: once, for
    both ways (the second's, flipped)"""
    for way in ways:
        way.find_missing()
    way_a, way_b = ways
    way_a.differs, way_b.differs = concurrent.futures.Future(), concurrent.futures.Future()

    def find(futures=(way_a.differs, way_b.differs)):
        try:
            changes = differing.find(way_a.src, way_a.dst)
        except Exception as error:
            for future in futures:
                future.set_exception(error)
        else:
            futures[0].set_result(changes)
            futures[1].set_result(differing.flipped(changes))
    threading.Thread(target=find, daemon=True).start()


# The sync menu's first line: whether the two are in sync (see syncstate.py), as each way finds
# their files
STATE = "Sync state"


def _state_line(ways, path_a, path_b):
    """The sync menu's line of whether the two are in sync, by what each way found (a
    picker.Skipped), the replicas by their short names (the breadcrumbs')"""
    names = replicanames.short_names([path_a, path_b])
    path_a, path_b = names[path_a], names[path_b]
    futures = [way.missing for way in ways]
    if not all(future.done() for future in futures):
        return picker.Skipped(picker.styled([("%s Comparing them..." % (syncstate.MARKS[syncstate.UNKNOWN],), 'grey')]))
    if any(future.exception() is not None for future in futures):
        return picker.Skipped(picker.styled([("%s Couldn't compare them" % (syncstate.MARKS[syncstate.UNKNOWN],), 'grey')]))
    only_a, only_b = [len(future.result().relpaths) for future in futures]
    state = syncstate.State(syncstate.found(only_a, only_b), only_a, only_b, None, [])
    mark, color = syncstate.mark(state)
    differ = ways[0].differs
    nr_differ = len(differ.result()) if differ.done() and differ.exception() is None else 0
    return picker.Skipped(picker.styled([(mark + " ", color), (syncstate.describe(state, path_a, path_b), color),
                                         ("; %s at the same paths %s" % (_files(nr_differ), _differ(nr_differ)) if nr_differ else "",
                                          differing.STYLE)]))


# How often the "loading" dots of a menu option change, in seconds
DOTS_INTERVAL = 0.4


class _Way(object):
    """One way of the sync: src's files that dst lacks (a future of Missing), found in the
    background, the replicas' indexes (elsewhere.Index, by replica), and which of src's files
    have the same contents as their matches"""
    def __init__(self, src, dst, indexes):
        self.src = src
        self.dst = dst
        self.indexes = indexes
        # Which of src's files' matches in dst have the same contents (see
        # elsewhere.check_contents()), kept so each is compared once
        self.checked = {}
        self.missing = None
        # A future of the files both have that differ, src's way (differing.find(), see _find_all())
        self.differs = None

    def find_missing(self):
        """Start finding them (again), on a thread of its own, which doesn't keep dirdelta from
        exiting"""
        self.missing = concurrent.futures.Future()
        threading.Thread(target=self._find_missing, args=(self.missing,), daemon=True).start()

    def _find_missing(self, missing):
        try:
            missing.set_result(replica_ops.find_missing(self.src, self.dst))
        except Exception as error:
            # Raised by result(), when the files are needed
            missing.set_exception(error)


class _Action(object):
    """A main menu option: the files of a way (interactive_dir_sync), from the replica at src_path to
    the one at dst_path. Their names are worked out each time, as a replica may be labeled meanwhile."""
    def __init__(self, src_path, dst_path, way, changes=None, only_differing=False):
        """With only_differing, it's the files that differ only (see DIFFER)"""
        self.src_path = src_path
        self.dst_path = dst_path
        self.way = way
        self.changes = changes
        self.only_differing = only_differing

    def shown_as(self):
        """The label, with how many files it's about, or that they're still being found. With none,
        it can't be picked (a picker.Disabled): it would only say so. Once the files are found
        again (after a live action), it may be picked again."""
        if self.only_differing:
            label = "%s at the same paths in both" % (DIFFER,)
        else:
            label = "Files only in %s" % (replicanames.full(self.src_path),)
        missing, differs = self.way.missing, self.way.differs
        if differs is None:
            # Not looked for
            differs = concurrent.futures.Future()
            differs.set_result({})
        if not missing.done() or (self.only_differing and not differs.done()):
            dots = int(time.monotonic() / DOTS_INTERVAL) % 4
            return "%s (loading%s)" % (label, '.' * dots)
        nr_differ = len(differs.result()) if differs.done() and differs.exception() is None else 0
        if self.only_differing:
            if differs.exception() is not None:
                return "%s (couldn't compare them)" % (label,)
            if nr_differ == 0:
                return picker.Disabled("%s: none" % (label,))
            return "%s (%s)" % (label, _files(nr_differ))
        if missing.exception() is not None:
            return "%s (couldn't count the files)" % (label,)
        count = len(missing.result().relpaths)
        # The ones that differ are in its picker too
        and_differ = ", and %d that %s" % (nr_differ, _differ(nr_differ)) if nr_differ else ""
        if count == 0 and not nr_differ:
            return picker.Disabled("%s: none, %s has them all" % (label, replicanames.full(self.dst_path)))
        return "%s (%s%s)" % (label, _files(count), and_differ)

    def run(self):
        """Returns whether the replicas' files changed meanwhile (see InteractiveDirSync)"""
        way = self.way
        sync = interactive_dir_sync.InteractiveDirSync(way.src, way.dst, way.missing,
                                                       way.indexes[way.src], way.indexes[way.dst],
                                                       way.checked, self.changes, way.differs,
                                                       self.only_differing)
        with picker.place(DIFFER if self.only_differing else "Files in %s" % (replicanames.full(self.src_path),)):
            sync.browse()
        self.was_read_anew = sync.was_read_anew
        return sync.has_changed


def _read_only_lines(replica, replica_path):
    """What can't be done with the replica, and what can, if it's read-only"""
    if not replica_ops.is_writable(replica):
        return ["%s is read-only (no write permission): you can still copy its files to the other replica, "
                "but dirdelta won't copy files into it, remove files from it or move them in it." % (replica_path,)
                ] + mounts.read_only_lines_of(replica_path)
    return []
