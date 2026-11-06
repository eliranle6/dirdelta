"""Sync mode: the menu of a pair of replicas, until it goes back to the start menu"""
from dirdelta.drive import drivemeta
from dirdelta.hashes import hashcache
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.screens import hashes_screen
from dirdelta.sync import replica_ops
from dirdelta.sync.sync_menu import BACK, SyncMenu  # noqa: F401 (BACK: the menu's, for its callers)
from dirdelta.trees import localdiskdirtree
from dirdelta.trees import paths
from dirdelta.trees import replicafactory
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.known import log_entries


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
    log_entries.note_seen(trees, known_replicas)
    replicas.save(known_replicas)
    # The local replicas' files' hashes, which find a file by its contents: hashed in the
    # background, if the user wants, and kept in each (see hashcache.use_replica())
    for tree in (dirtree_a, dirtree_b):
        if localdiskdirtree.is_local(tree):
            hashcache.use_replica(tree.fullpath())
    if not hashes_screen.offer(hashes_screen.prepare([dirtree_a, dirtree_b])):
        return
    changes = log_entries.Changes()
    # A Drive replica's file list is kept in it too, as it changes (see drivemeta.py)
    with drivemeta.kept([(args.dir_a_path, dirtree_a), (args.dir_b_path, dirtree_b)]):
        result = _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path, known_replicas, changes)
    log_entries.offer_entries(changes, trees, known_replicas)
    return result


def _sync(replica_a, replica_b, replica_a_path, replica_b_path, known_replicas=None, changes=None):
    """The main menu, until the user quits. With known_replicas (a Replicas, saved when changed),
    it also makes the pair a favorite, or not. changes: where the files changed live are noted (a
    log_entries.Changes), if anywhere."""
    return SyncMenu(replica_a, replica_b, replica_a_path, replica_b_path, known_replicas, changes).run()
