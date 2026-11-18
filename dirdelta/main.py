"""dirdelta's entry point: the arguments, then the start menu (no path), picker mode (one path), sync
mode (two) or sorting an inbox (--sort); each local replica's volume is checked to be mounted first"""
import argparse
import os
import sys

from dirdelta.trees import localscan
from dirdelta.screens import choose_replicas
from dirdelta.sync import dirsync_main
from dirdelta import dirpick_main
from dirdelta.drive import drivecache
from dirdelta import inbox
from dirdelta.known import mounts
from dirdelta.util import programs
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.trees import replicafactory


def parse_args():
    parser = argparse.ArgumentParser()
    # Neither: a menu chooses the two (from the favorites and the history, or each on its own)
    parser.add_argument('dir_a_path', nargs='?', default=None)
    parser.add_argument('dir_b_path', nargs='?', default=None)
    parser.add_argument("-x", "--execute", default=None)
    # With two paths: sort the first (an inbox) into the second (a sorted tree), see inbox.py
    parser.add_argument("-s", "--sort", action='store_true')
    parser.add_argument("-m", "--max-depth", type=int, default=localscan.DEFAULT_MAX_DEPTH)
    # The daemon: the web version (on the network, at PORT), and the watch for replicas appearing
    parser.add_argument("--serve", action='store_true')
    parser.add_argument("--port", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.serve:
        # (Imported only here: the daemon's server, which the terminal's dirdelta doesn't need)
        from dirdelta.web import daemon
        daemon.run(args.port)
        return
    # No curses here: the pickers (treepicker) take over the terminal while they run, and messages
    # are plain prints in between
    try:
        picked_path = _run(args)
    except (programs.ProgramError, drivecache.DriveCacheError, replicas.ReplicasError,
            inbox.InboxError, mounts.MountsError, replicafactory.NotADirError) as error:
        sys.exit('dirdelta: %s' % (error,))

    if picked_path is not None:
        dirpick_main.use_picked_path(picked_path, args.execute)


def _run(args):
    # Run the right main (no args is choosing the dirs to synchronize, one arg is dir picker, two
    # args are dirs synchronization, then the start menu, as after one chosen there)
    if args.dir_a_path is not None and args.dir_b_path is not None and not args.sort:
        if _ready(args.dir_a_path, args.dir_b_path):
            dirsync_main.run(args)
        args = argparse.Namespace(**dict(vars(args), dir_a_path=None, dir_b_path=None))
    if args.dir_a_path is None:
        return start_menu(args)
    elif args.sort:
        if args.dir_b_path is None:
            sys.exit('dirdelta: --sort takes two paths: the inbox, and the sorted tree')
        if _ready(args.dir_a_path, args.dir_b_path):
            inbox.run(args.dir_a_path, args.dir_b_path, replicas.load())
        return None
    return dirpick_main.run(args) if _ready(args.dir_a_path) else None


def _default_args():
    return argparse.Namespace(dir_a_path=None, dir_b_path=None, execute=None, sort=False,
                              max_depth=localscan.DEFAULT_MAX_DEPTH)


def start_menu(args=None):
    """The start menu, again after a sync or a sort (or going back from one), until Quit (args: as
    parse_args()'s, without paths; the defaults if None)"""
    args = args or _default_args()
    while True:
        chosen = choose_replicas.run(replicas.load())
        if chosen is None:
            return None
        if isinstance(chosen, choose_replicas.Sort):
            run_sort(chosen.inbox, chosen.root)
        else:
            run_pair(chosen[0], chosen[1], args)


def run_pair(path_a, path_b, args=None):
    """Sync the replicas at path_a and path_b, once their volumes are mounted and they're there (args:
    as parse_args()'s, whose paths are ignored; the defaults if None)"""
    # The paths in a copy of args (args itself is left as it was parsed)
    chosen_args = argparse.Namespace(**dict(vars(args or _default_args()), dir_a_path=path_a, dir_b_path=path_b))
    if _ready(path_a, path_b) and choose_replicas.are_there((path_a, path_b)):
        dirsync_main.run(chosen_args)


def run_sort(inbox_path, root_path):
    """Sort the inbox at inbox_path into the sorted tree at root_path, once they're there"""
    if _ready(inbox_path, root_path) and choose_replicas.are_there((inbox_path, root_path)):
        inbox.run(inbox_path, root_path, replicas.load())


def _ready(*replica_paths):
    """Whether the replicas' volumes are mounted (see mounts.py: the user is asked to mount one that
    isn't, and may not), remembering how they are, for next time"""
    for path in replica_paths:
        if not mounts.ensure_mounted(path):
            return False
    # What they're on may be another disk now
    replicanames.forget()
    for path in replica_paths:
        if os.path.isdir(path):
            mounts.remember(path)
    return True


if __name__ == "__main__":
    main()
