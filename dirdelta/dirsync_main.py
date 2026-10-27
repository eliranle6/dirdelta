import concurrent.futures
import os
import threading
import time

from dirdelta import dryrun
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
    # Each way, what can be done with the files in one replica that aren't in the other: copy them
    # into a writable one (between a local dir and anything: not within Drive) and remove them
    # (from a writable one). Their pickers
    # show those files, so viewing them is offered only when neither can be done. Each way's
    # files are found once, in the background, and each option says how many there are once they
    # are.
    ways = [_Way(replica_a, replica_b), _Way(replica_b, replica_a)]
    copies, removes, views = [], [], []
    for way, src_path, dst_path in ((ways[0], replica_a_path, replica_b_path),
                                    (ways[1], replica_b_path, replica_a_path)):
        can_copy = _is_writable(way.dst) and (_is_local(way.src) or _is_local(way.dst))
        if can_copy:
            copies.append(_Action("Copy files from %s to %s" % (src_path, dst_path), way,
                                  lambda count: "the %s it lacks" % (_files(count),),
                                  interactive_dir_sync.InteractiveDirSync.COPY))
        if _is_writable(way.src):
            removes.append(_Action("Remove files from %s" % (src_path,), way,
                                   lambda count, dst_path=dst_path: "the %s %s lacks" % (_files(count), dst_path),
                                   interactive_dir_sync.InteractiveDirSync.REMOVE))
        elif not can_copy:
            views.append(_Action("View files in %s, not %s" % (src_path, dst_path), way,
                                 _files))
    actions = {action.label: action for action in copies + removes + views}
    for way in ways:
        way.find_missing()

    # Present sync options until user quits
    while True:
        favorite_options = []
        if known_replicas is not None:
            is_favorite = known_replicas.is_favorite(replica_a_path, replica_b_path)
            favorite_options = [REMOVE_FAVORITE if is_favorite else ADD_FAVORITE]
        option = picker.pick_option(list(actions) + favorite_options + [QUIT],
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
        actions[option].run()
        # Copying and removing change the files (unless it's a dry run), and so what each lacks
        if actions[option].action is not None and not dryrun.DRYRUN:
            for way in ways:
                way.find_missing()


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


# How often the "loading" dots of a menu option change, in seconds
DOTS_INTERVAL = 0.4


class _Way(object):
    """One way of the sync: src's files that dst lacks (a future of Missing), found in the
    background"""
    def __init__(self, src, dst):
        self.src = src
        self.dst = dst
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
    """A main menu option: an InteractiveDirSync's sync(action) of a way, or its view_diff() if
    action is None. describe_count(count) says how many files it's about (e.g. "3 files")."""
    def __init__(self, label, way, describe_count, action=None):
        self.label = label
        self.way = way
        self.describe_count = describe_count
        self.action = action

    def shown_as(self):
        """The label, with how many files it's about, or that they're still being found"""
        missing = self.way.missing
        if not missing.done():
            dots = int(time.monotonic() / DOTS_INTERVAL) % 4
            return "%s (loading%s)" % (self.label, '.' * dots)
        if missing.exception() is not None:
            return "%s (couldn't count the files)" % (self.label,)
        return "%s (%s)" % (self.label, self.describe_count(len(missing.result().relpaths)))

    def run(self):
        sync = interactive_dir_sync.InteractiveDirSync(self.way.src, self.way.dst, self.way.missing)
        if self.action is None:
            sync.view_diff()
        else:
            sync.sync(self.action)


def _is_local(replica):
    return isinstance(replica, localdiskdirtree.LocalDiskDirTree)


def _is_writable(replica):
    """Whether files can be copied into the replica and removed from it: Drive, or a local dir with
    write permission (none on a read-only mount)"""
    return not _is_local(replica) or os.access(replica.fullpath(), os.W_OK)


def _read_only_lines(replica, replica_path):
    """Why nothing will be copied into or removed from the replica, if it's read-only"""
    if not _is_writable(replica):
        return ["%s is read-only (no write permission): dirdelta won't copy files into it or "
                "remove files from it." % (replica_path,)]
    return []
