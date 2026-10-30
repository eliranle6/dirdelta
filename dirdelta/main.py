import argparse
import os
import sys

from dirdelta import choose_replicas
from dirdelta import dirsync_main
from dirdelta import dirpick_main
from dirdelta import drivecache
from dirdelta import inbox
from dirdelta import mounts
from dirdelta import programs
from dirdelta import replicas


def parse_args():
    parser = argparse.ArgumentParser()
    # Neither: a menu chooses the two (from the favorites and the history, or each on its own)
    parser.add_argument('dir_a_path', nargs='?', default=None)
    parser.add_argument('dir_b_path', nargs='?', default=None)
    parser.add_argument("-x", "--execute", default=None)
    # With two paths: sort the first (an inbox) into the second (a sorted tree), see inbox.py
    parser.add_argument("-s", "--sort", action='store_true')
    parser.add_argument("-m", "--max-depth", type=int, default=20)
    return parser.parse_args()


def main():
    args = parse_args()
    # No curses here: the pickers (treepicker) take over the terminal while they run, and messages
    # are plain prints in between
    try:
        picked_path = _run(args)
    except (programs.ProgramError, drivecache.DriveCacheError, replicas.ReplicasError,
            inbox.InboxError, mounts.MountsError) as error:
        sys.exit('dirdelta: %s' % (error,))

    if picked_path is not None:
        dirpick_main.use_picked_path(picked_path, args.execute)


def _run(args):
    # Run the right main (no args is choosing the dirs to synchronize, one arg is dir picker, two
    # args are dirs synchronization)
    if args.dir_a_path is None:
        known_replicas = replicas.load()
        chosen = choose_replicas.run(known_replicas)
        if chosen is None:
            return None
        if isinstance(chosen, choose_replicas.Sort):
            if _ready(chosen.inbox, chosen.root):
                inbox.run(chosen.inbox, chosen.root, known_replicas)
            return None
        args.dir_a_path, args.dir_b_path = chosen
    elif args.sort:
        if args.dir_b_path is None:
            sys.exit('dirdelta: --sort takes two paths: the inbox, and the sorted tree')
        if _ready(args.dir_a_path, args.dir_b_path):
            inbox.run(args.dir_a_path, args.dir_b_path, replicas.load())
        return None
    elif args.dir_b_path is None:
        return dirpick_main.run(args) if _ready(args.dir_a_path) else None
    if _ready(args.dir_a_path, args.dir_b_path):
        dirsync_main.run(args)
    return None


def _ready(*replica_paths):
    """Whether the replicas' volumes are mounted (see mounts.py: the user is asked to mount one that
    isn't, and may not), remembering how they are, for next time"""
    for path in replica_paths:
        if not mounts.ensure_mounted(path):
            return False
    for path in replica_paths:
        if os.path.isdir(path):
            mounts.remember(path)
    return True


if __name__ == "__main__":
    main()
