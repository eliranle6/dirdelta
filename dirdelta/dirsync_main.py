import localdiskdirtree
import interactive_dir_sync
import menu
import utils


def run(args):
    dirtree_a = utils.create_dirtree_from_arg(args.dir_a_path)
    dirtree_b = utils.create_dirtree_from_arg(args.dir_b_path)
    _sync(dirtree_a, dirtree_b, args.dir_a_path, args.dir_b_path)


def _sync_from_src_to_dst(src, dst):
    dirsync = interactive_dir_sync.InteractiveDirSync(src, dst)
    dirsync.sync()


def _view_diff(src, dst):
    dirsync = interactive_dir_sync.InteractiveDirSync(src, dst)
    dirsync.view_diff(src, dst)


def _sync(replica_a, replica_b, replica_a_path, replica_b_path):
    QUIT = "Quit"
    actions = [
        ("View files in %s, not %s" % (replica_a_path, replica_b_path),
         lambda: _view_diff(src=replica_a, dst=replica_b)),
        ("View files in %s, not %s" % (replica_b_path, replica_a_path),
         lambda: _view_diff(src=replica_b, dst=replica_a)),
        (QUIT, None),
    ]

    # Allow sync (copy/remove) only if both dirs are in local disk
    if (isinstance(replica_a, localdiskdirtree.LocalDiskDirTree)
        and isinstance(replica_b, localdiskdirtree.LocalDiskDirTree)):
        actions.extend([
            ("Remove/Copy files from %s to %s" % (replica_a_path, replica_b_path),
             lambda: _sync_from_src_to_dst(src=replica_a, dst=replica_b)),
            ("Remove/Copy files from %s to %s" % (replica_b_path, replica_a_path),
             lambda: _sync_from_src_to_dst(src=replica_b, dst=replica_a)),
        ])

    # Present sync options until user quits
    option = None
    while option != QUIT:
        option = menu.run_menu(actions)
        if option is None:
            break
