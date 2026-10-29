import concurrent.futures
import threading
import time

from dirdelta import clouddirtree
from dirdelta import dryrun
from dirdelta import elsewhere
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicas
from dirdelta import utils


def run(args):
    if not paths.is_cloud_path(args.dir_a_path) and not paths.is_cloud_path(args.dir_b_path):
        # Two local dirs: each action diffs them with dirdiff, which scans them anew, so there's
        # nothing to scan here
        for path in (args.dir_a_path, args.dir_b_path):
            utils.validate_dir(path)
        dirtree_a = localdiskdirtree.LocalDiskDirTree(args.dir_a_path, True, args.max_depth)
        dirtree_b = localdiskdirtree.LocalDiskDirTree(args.dir_b_path, True, args.max_depth)
    else:
        dirtree_a = utils.create_dirtree_from_arg(args.dir_a_path, args.max_depth)
        dirtree_b = utils.create_dirtree_from_arg(args.dir_b_path, args.max_depth)
        warnings = scan_errors_warning(dirtree_a) + scan_errors_warning(dirtree_b)
        if warnings:
            messages.show("Warning: find couldn't read everything", warnings, dryrun.label(), 'red')
    # Both are dirs (or Drive's), so they're the history's latest
    known_replicas = replicas.load()
    known_replicas.record(args.dir_a_path, args.dir_b_path)
    replicas.save(known_replicas)
    _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path, known_replicas)


def scan_errors_warning(tree):
    """A warning's lines if scanning the (local) tree couldn't read everything; else none."""
    return localdiskdirtree.scan_warning(tree.fullpath(), getattr(tree, 'scan_errors', []))


def _sync(replica_a, replica_b, replica_a_path, replica_b_path, known_replicas=None):
    """The main menu, until the user quits. With known_replicas (a Replicas, saved when changed),
    it also makes the pair a favorite, or not."""
    QUIT = "Quit"
    ADD_FAVORITE = "Add to favorites"
    REMOVE_FAVORITE = "Remove from favorites"
    read_only = _read_only_lines(replica_a, replica_a_path) + _read_only_lines(replica_b, replica_b_path)
    if read_only:
        messages.show("Read-only", read_only, dryrun.label())
    # Each way, the files in one replica that aren't in the other, to pick and then copy, remove or
    # rename (interactive_dir_sync): found once, in the background, with each option saying how
    # many there are once they are. Each replica's files by name (for finding where the other has a
    # file of a name) are kept, so they're listed once.
    indexes = {replica: elsewhere.Index(replica) for replica in (replica_a, replica_b)}
    ways = [_Way(replica_a, replica_b, indexes), _Way(replica_b, replica_a, indexes)]
    actions = {}
    for way, src_path, dst_path in ((ways[0], replica_a_path, replica_b_path),
                                    (ways[1], replica_b_path, replica_a_path)):
        label = "Files in %s, not in %s" % (src_path, dst_path)
        actions[label] = _Action(label, way, "none, %s has them all" % (dst_path,))
    # A cloud replica's folder can be read anew from Drive, if Drive changed since the cache was made
    refreshes = {"Refresh %s from Google Drive" % (path,): replica
                 for replica, path in ((replica_a, replica_a_path), (replica_b, replica_b_path))
                 if isinstance(replica, clouddirtree.CloudDirTree)}
    for way in ways:
        way.find_missing()

    # Present sync options until user quits
    while True:
        favorite_options = []
        if known_replicas is not None:
            is_favorite = known_replicas.is_favorite(replica_a_path, replica_b_path)
            favorite_options = [REMOVE_FAVORITE if is_favorite else ADD_FAVORITE]
        option = picker.pick_option(list(actions) + list(refreshes) + favorite_options + [QUIT],
                                    shown_as=lambda: {label: action.shown_as()
                                                      for label, action in actions.items()})
        if option in (None, QUIT):
            break
        if option in (ADD_FAVORITE, REMOVE_FAVORITE):
            known_replicas.toggle_favorite(replica_a_path, replica_b_path)
            replicas.save(known_replicas)
            continue
        # An action may change the trees (or dirs) that the other way may still be diffing, so
        # both are waited for
        if not all(way.missing.done() for way in ways):
            messages.print_line("Finding the files that each lacks...")
        concurrent.futures.wait([way.missing for way in ways])
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


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


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
    """A main menu option: the files of a way (interactive_dir_sync), nothing saying that there are
    none, when it can't be picked"""
    def __init__(self, label, way, nothing):
        self.label = label
        self.way = way
        self.nothing = nothing

    def shown_as(self):
        """The label, with how many files it's about, or that they're still being found. With none,
        it can't be picked (a picker.Disabled): it would only say so. Once the files are found
        again (after a live action), it may be picked again."""
        missing = self.way.missing
        if not missing.done():
            dots = int(time.monotonic() / DOTS_INTERVAL) % 4
            return "%s (loading%s)" % (self.label, '.' * dots)
        if missing.exception() is not None:
            return "%s (couldn't count the files)" % (self.label,)
        count = len(missing.result().relpaths)
        if count == 0:
            return picker.Disabled("%s: %s" % (self.label, self.nothing))
        return "%s (%s)" % (self.label, _files(count))

    def run(self):
        """Returns whether the replicas' files changed meanwhile (see InteractiveDirSync)"""
        way = self.way
        sync = interactive_dir_sync.InteractiveDirSync(way.src, way.dst, way.missing,
                                                       way.indexes[way.src], way.indexes[way.dst],
                                                       way.checked)
        sync.browse()
        return sync.has_changed


def _read_only_lines(replica, replica_path):
    """Why nothing will be copied into, removed from or moved in the replica, if it's read-only"""
    if not interactive_dir_sync.is_writable(replica):
        return ["%s is read-only (no write permission): dirdelta won't copy files into it, "
                "remove files from it or move them in it." % (replica_path,)]
    return []
