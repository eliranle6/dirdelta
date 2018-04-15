import os

import cursesswitch
import treepicker
import replicas_from_args
import interactive_dir_sync
import search_supplement_replicas


def sync_from_src_to_dst(src, dst):
    dirsync = interactive_dir_sync.InteractiveDirSync(src, dst)
    dirsync.sync()


def sync(replica_a, replica_b):
    A_TO_B = "Remove/Copy files from %s to %s" % (replica_a, replica_b)
    B_TO_A = "Remove/Copy files from %s to %s" % (replica_b, replica_a)
    QUIT = "Quit"
    options = [A_TO_B, B_TO_A, QUIT]

    option = None
    picker = treepicker.optionpicker.OptionPickerByMenuTraverse(options)
    while option != QUIT:
        option = picker.pick_one()
        if option == A_TO_B:
            sync_from_src_to_dst(src=replica_a, dst=replica_b)
        elif option == B_TO_A:
            sync_from_src_to_dst(src=replica_b, dst=replica_a)
        elif option is None:
            break


def main():
    replica_a_path, replica_b_path = replicas_from_args.get()
    replica_a_path, replica_b_path = search_supplement_replicas.search(replica_a_path, replica_b_path)
    sync(replica_a_path, replica_b_path)


if __name__ == "__main__":
    if os.getenv('MODE') == 'static':
        main()
    else:
        cursesswitch.wrapper(main)
