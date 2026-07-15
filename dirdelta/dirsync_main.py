import localdiskdirtree
import treepicker
import interactive_dir_sync
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
    VIEW_DIFF_A_NOT_B = "View files in %s, not %s" % (replica_a_path, replica_b_path)
    VIEW_DIFF_B_NOT_A = "View files in %s, not %s" % (replica_b_path, replica_a_path)
    A_TO_B = "Remove/Copy files from %s to %s" % (replica_a_path, replica_b_path)
    B_TO_A = "Remove/Copy files from %s to %s" % (replica_b_path, replica_a_path)
    QUIT = "Quit"
    options = [VIEW_DIFF_A_NOT_B, VIEW_DIFF_B_NOT_A, QUIT]

    # Allow sync (copy/remove) only if both dirs are in local disk
    if (isinstance(replica_a, localdiskdirtree.LocalDiskDirTree)
        and isinstance(replica_b, localdiskdirtree.LocalDiskDirTree)):
        options.extend([A_TO_B, B_TO_A])

    # Present sync options until user quits
    option = None
    picker = treepicker.optionpicker.OptionPickerByMenuTraverse(options)
    while option != QUIT:
        option = picker.pick_one()
        if option == A_TO_B:
            _sync_from_src_to_dst(src=replica_a, dst=replica_b)
        elif option == B_TO_A:
            _sync_from_src_to_dst(src=replica_b, dst=replica_a)
        elif option == VIEW_DIFF_A_NOT_B:
            _view_diff(src=replica_a, dst=replica_b)
        elif option == VIEW_DIFF_B_NOT_A:
            _view_diff(src=replica_b, dst=replica_a)
        elif option is None:
            break
