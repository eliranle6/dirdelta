import concurrent.futures
import datetime
import threading
import time

from dirdelta import clouddirtree
from dirdelta import drivemeta
from dirdelta import dryrun
from dirdelta import elsewhere
from dirdelta import hashcache
from dirdelta import hashes_screen
from dirdelta import hashing
from dirdelta import interactive_dir_sync
from dirdelta import label_screen
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicainfo
from dirdelta import replicalog
from dirdelta import replicanames
from dirdelta import replicas
from dirdelta import syncstate
from dirdelta import replicafactory
from dirdelta import text


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
        warnings = scan_errors_warning(dirtree_a) + scan_errors_warning(dirtree_b)
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
        if hashes_screen.is_local(tree):
            hashcache.use_replica(tree.fullpath())
    if not hashes_screen.offer(hashes_screen.prepare([dirtree_a, dirtree_b])):
        return
    changes = replicalog.Changes()
    # A Drive replica's file list is kept in it too, as it changes (see drivemeta.py)
    with drivemeta.kept([(args.dir_a_path, dirtree_a), (args.dir_b_path, dirtree_b)]):
        result = _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path, known_replicas, changes)
    replicalog.offer_entries(changes, trees, known_replicas)
    return result


def scan_errors_warning(tree):
    """A warning's lines if scanning the (local) tree couldn't read everything; else none."""
    return localdiskdirtree.scan_warning(tree.fullpath(), getattr(tree, 'scan_errors', []))


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
    # A cloud replica's folder can be read anew from Drive, if Drive changed since the cache was made
    refreshes = {"Refresh %s file list from Google Drive" % (path,): replica
                 for replica, path in ((replica_a, replica_a_path), (replica_b, replica_b_path))
                 if isinstance(replica, clouddirtree.CloudDirTree)}
    # A local one can be scanned anew, if its files changed meanwhile, outside dirdelta
    rescans = {"Rescan %s" % (path,): replica for replica, path in ((replica_a, replica_a_path), (replica_b, replica_b_path))
               if hashes_screen.is_local(replica)}
    for way in ways:
        way.find_missing()
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
        if not all(way.missing.done() for way in ways):
            messages.print_line("Finding the files that each lacks...")
        concurrent.futures.wait([way.missing for way in ways])
        if option in rescans:
            if _rescan(rescans[option]):
                indexes[rescans[option]].invalidate()
                for way in ways:
                    # Its files may have other contents now
                    way.checked.clear()
                    way.find_missing()
                for job in hashes_screen.jobs_of([rescans[option]]):
                    job.scan_in_background()
            continue
        if option in refreshes:
            if interactive_dir_sync.refresh_replica(refreshes[option]):
                indexes[refreshes[option]].invalidate()
                for way in ways:
                    # Its files may have other contents now
                    way.checked.clear()
                    way.find_missing()
            continue
        # Copying, removing and renaming change the files (unless it's a dry run), and so what each
        # lacks, and so does reading a replica anew from Drive (in the file picker)
        if actions[option].run():
            for way in ways:
                way.find_missing()
            # Files copied into a local replica (or moved in it) are hashed too
            for job in jobs:
                job.scan_in_background()


_files = text.files

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
    return picker.Skipped(picker.styled([(mark + " ", color), (syncstate.describe(state, path_a, path_b), color)]))


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

    def find_missing(self):
        """Start finding them (again), on a thread of its own, which doesn't keep dirdelta from
        exiting"""
        self.missing = concurrent.futures.Future()
        threading.Thread(target=self._find_missing, args=(self.missing,), daemon=True).start()

    def _find_missing(self, missing):
        try:
            missing.set_result(interactive_dir_sync.find_missing(self.src, self.dst))
        except Exception as error:
            # Raised by result(), when the files are needed
            missing.set_exception(error)


class _Action(object):
    """A main menu option: the files of a way (interactive_dir_sync), from the replica at src_path to
    the one at dst_path. Their names are worked out each time, as a replica may be labeled meanwhile."""
    def __init__(self, src_path, dst_path, way, changes=None):
        self.src_path = src_path
        self.dst_path = dst_path
        self.way = way
        self.changes = changes

    def shown_as(self):
        """The label, with how many files it's about, or that they're still being found. With none,
        it can't be picked (a picker.Disabled): it would only say so. Once the files are found
        again (after a live action), it may be picked again."""
        label = "Files only in %s" % (replicanames.full(self.src_path),)
        missing = self.way.missing
        if not missing.done():
            dots = int(time.monotonic() / DOTS_INTERVAL) % 4
            return "%s (loading%s)" % (label, '.' * dots)
        if missing.exception() is not None:
            return "%s (couldn't count the files)" % (label,)
        count = len(missing.result().relpaths)
        if count == 0:
            return picker.Disabled("%s: none, %s has them all" % (label, replicanames.full(self.dst_path)))
        return "%s (%s)" % (label, _files(count))

    def run(self):
        """Returns whether the replicas' files changed meanwhile (see InteractiveDirSync)"""
        way = self.way
        sync = interactive_dir_sync.InteractiveDirSync(way.src, way.dst, way.missing,
                                                       way.indexes[way.src], way.indexes[way.dst],
                                                       way.checked, self.changes)
        with picker.place("Files in %s" % (replicanames.full(self.src_path),)):
            sync.browse()
        return sync.has_changed


def _rescan(replica):
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


def _read_only_lines(replica, replica_path):
    """What can't be done with the replica, and what can, if it's read-only"""
    if not interactive_dir_sync.is_writable(replica):
        return ["%s is read-only (no write permission): you can still copy its files to the other replica, "
                "but dirdelta won't copy files into it, remove files from it or move them in it." % (replica_path,)]
    return []
