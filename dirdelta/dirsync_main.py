import functools
import os

from dirdelta import dryrun
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
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
    _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path)


def scan_errors_warning(tree):
    """A warning's lines if scanning the (local) tree couldn't read everything; else none."""
    return localdiskdirtree.scan_warning(tree.fullpath(), getattr(tree, 'scan_errors', []))


def _sync(replica_a, replica_b, replica_a_path, replica_b_path):
    QUIT = "Quit"
    read_only = _read_only_lines(replica_a, replica_a_path) + _read_only_lines(replica_b, replica_b_path)
    if read_only:
        messages.show("Read-only", read_only, dryrun.label())
    # Each way, what can be done with the files in one replica that aren't in the other: copy them
    # (from a local dir into a writable one) and remove them (from a writable one). Their pickers
    # show those files, so viewing them is offered only when neither can be done.
    copies, removes, views = [], [], []
    for src, dst, src_path, dst_path in ((replica_a, replica_b, replica_a_path, replica_b_path),
                                         (replica_b, replica_a, replica_b_path, replica_a_path)):
        sync = interactive_dir_sync.InteractiveDirSync(src, dst)
        can_copy = isinstance(src, localdiskdirtree.LocalDiskDirTree) and _is_writable(dst)
        if can_copy:
            copies.append(("Copy files from %s to %s (the ones it lacks)" % (src_path, dst_path),
                           functools.partial(sync.sync, interactive_dir_sync.InteractiveDirSync.COPY)))
        if _is_writable(src):
            removes.append(("Remove files from %s (the ones %s lacks)" % (src_path, dst_path),
                            functools.partial(sync.sync, interactive_dir_sync.InteractiveDirSync.REMOVE)))
        elif not can_copy:
            views.append(("View files in %s, not %s" % (src_path, dst_path), sync.view_diff))
    actions = copies + removes + views
    actions.append((QUIT, None))

    # Present sync options until user quits
    handlers = dict(actions)
    while True:
        option = picker.pick_option([label for label, _ in actions])
        if option in (None, QUIT):
            break
        handlers[option]()


def _is_writable(replica):
    """Whether files can be copied into the replica and removed from it: a local dir with write
    permission (none on a read-only mount). Drive is read-only: dirdelta reads it with a read-only
    scope, and has no code to upload or remove files there."""
    return (isinstance(replica, localdiskdirtree.LocalDiskDirTree)
            and os.access(replica.fullpath(), os.W_OK))


def _read_only_lines(replica, replica_path):
    """Why nothing will be copied into or removed from the replica, if it's read-only"""
    if not isinstance(replica, localdiskdirtree.LocalDiskDirTree):
        return ["%s is on Google Drive, which dirdelta only reads: it can't copy files into it or "
                "out of it, or remove files from it." % (replica_path,)]
    if not _is_writable(replica):
        return ["%s is read-only (no write permission): dirdelta won't copy files into it or "
                "remove files from it." % (replica_path,)]
    return []
