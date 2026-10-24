from dirdelta import localdiskdirtree
from dirdelta import interactive_dir_sync
from dirdelta import menu
from dirdelta import messages
from dirdelta import utils


# How many of find's error messages a warning lists
MAX_SCAN_ERRORS_SHOWN = 3


def run(args):
    dirtree_a = utils.create_dirtree_from_arg(args.dir_a_path, args.max_depth)
    dirtree_b = utils.create_dirtree_from_arg(args.dir_b_path, args.max_depth)
    for tree in (dirtree_a, dirtree_b):
        warn_about_scan_errors(tree)
    _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path)


def warn_about_scan_errors(tree):
    """Warn if scanning the (local) tree couldn't read everything, since then the diff may list
    files as missing that are there, or miss some."""
    errors = getattr(tree, 'scan_errors', [])
    if not errors:
        return
    messages.print_line("Warning: find couldn't read everything in %s (%d errors), so the diff may "
                        "be wrong:" % (tree.fullpath(), len(errors)), 'red')
    for error in errors[:MAX_SCAN_ERRORS_SHOWN]:
        messages.print_line("  " + error, 'red')
    if len(errors) > MAX_SCAN_ERRORS_SHOWN:
        messages.print_line("  (and %d more)" % (len(errors) - MAX_SCAN_ERRORS_SHOWN,), 'red')


def _sync_from_src_to_dst(src, dst, action):
    dirsync = interactive_dir_sync.InteractiveDirSync(src, dst)
    dirsync.sync(action)


def _view_diff(src, dst):
    dirsync = interactive_dir_sync.InteractiveDirSync(src, dst)
    dirsync.view_diff(src, dst)


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
             lambda: _sync_from_src_to_dst(src=replica_a, dst=replica_b, action=copy)),
            ("Copy files from %s to %s (the ones it lacks)" % (replica_b_path, replica_a_path),
             lambda: _sync_from_src_to_dst(src=replica_b, dst=replica_a, action=copy)),
            ("Remove files from %s (the ones %s lacks)" % (replica_a_path, replica_b_path),
             lambda: _sync_from_src_to_dst(src=replica_a, dst=replica_b, action=remove)),
            ("Remove files from %s (the ones %s lacks)" % (replica_b_path, replica_a_path),
             lambda: _sync_from_src_to_dst(src=replica_b, dst=replica_a, action=remove)),
        ]
    else:
        actions = [
            ("View files in %s, not %s" % (replica_a_path, replica_b_path),
             lambda: _view_diff(src=replica_a, dst=replica_b)),
            ("View files in %s, not %s" % (replica_b_path, replica_a_path),
             lambda: _view_diff(src=replica_b, dst=replica_a)),
        ]
    actions.append((QUIT, None))

    # Present sync options until user quits
    option = None
    while option != QUIT:
        option = menu.run_menu(actions)
        if option is None:
            break
