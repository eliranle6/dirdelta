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
    # Copying and removing only between dirs on the local disk. Each acts on the files in one dir
    # that aren't in the other, and its picker shows them, so viewing them is offered only where
    # it's all there is (a cloud replica).
    if (isinstance(replica_a, localdiskdirtree.LocalDiskDirTree)
        and isinstance(replica_b, localdiskdirtree.LocalDiskDirTree)):
        copy = interactive_dir_sync.InteractiveDirSync.COPY
        remove = interactive_dir_sync.InteractiveDirSync.REMOVE
        actions = [
            ("Copy files from %s to %s (the ones it lacks)" % (replica_a_path, replica_b_path),
             lambda: interactive_dir_sync.InteractiveDirSync(replica_a, replica_b).sync(copy)),
            ("Copy files from %s to %s (the ones it lacks)" % (replica_b_path, replica_a_path),
             lambda: interactive_dir_sync.InteractiveDirSync(replica_b, replica_a).sync(copy)),
            ("Remove files from %s (the ones %s lacks)" % (replica_a_path, replica_b_path),
             lambda: interactive_dir_sync.InteractiveDirSync(replica_a, replica_b).sync(remove)),
            ("Remove files from %s (the ones %s lacks)" % (replica_b_path, replica_a_path),
             lambda: interactive_dir_sync.InteractiveDirSync(replica_b, replica_a).sync(remove)),
        ]
    else:
        actions = [
            ("View files in %s, not %s" % (replica_a_path, replica_b_path),
             lambda: interactive_dir_sync.InteractiveDirSync(replica_a, replica_b).view_diff()),
            ("View files in %s, not %s" % (replica_b_path, replica_a_path),
             lambda: interactive_dir_sync.InteractiveDirSync(replica_b, replica_a).view_diff()),
        ]
    actions.append((QUIT, None))

    # Present sync options until user quits
    handlers = dict(actions)
    while True:
        option = picker.pick_option([label for label, _ in actions])
        if option in (None, QUIT):
            break
        handlers[option]()
