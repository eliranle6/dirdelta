import argparse
import os
import sys

from dirdelta import dirsync_main
from dirdelta import dirpick_main
from dirdelta import programs


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('dir_a_path', default=os.getcwd())  # Mandatory
    parser.add_argument('dir_b_path', nargs='?', default=None)  # Optional
    parser.add_argument("-x", "--execute", default=None)
    parser.add_argument("-m", "--max-depth", type=int, default=20)
    return parser.parse_args()


def main():
    args = parse_args()
    # No curses here: the pickers (dirpicker) take over the terminal while they run, and messages
    # are plain prints in between
    try:
        picked_path = _run(args)
    except programs.ProgramError as error:
        sys.exit('dirdelta: %s' % (error,))

    if picked_path is not None:
        dirpick_main.use_picked_path(picked_path, args.execute)


def _run(args):
    # Run the right main (one arg is dir picker, two args are dirs synchronization)
    if args.dir_b_path is None:
        return dirpick_main.run(args)
    dirsync_main.run(args)
    return None


if __name__ == "__main__":
    main()
