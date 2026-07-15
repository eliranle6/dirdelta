import argparse
import os

import cursesswitch
import dirsync_main
import dirpick_main


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('dir_a_path', default=os.getcwd())  # Mandatory
    parser.add_argument('dir_b_path', nargs='?', default=None)  # Optional
    parser.add_argument("-x", "--execute", default=None)
    parser.add_argument("-m", "--max-depth", default=20)
    return parser.parse_args()


def main():
    args = parse_args()

    # Run the right main (one arg is dir picker, two args are dirs synchronization)
    if args.dir_b_path is None:
        dirpick_main.run(args)
    else:
        dirsync_main.run(args)


if __name__ == "__main__":
    if os.getenv('MODE') == 'static':
        main()
    else:
        cursesswitch.wrapper(main)
