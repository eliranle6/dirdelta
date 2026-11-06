"""Picker mode: pick a file or dir under a path, then print it, or run a program (-x) on it"""
import os

from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.trees import replicafactory


def run(args):
    """Let the user pick a file or dir under args.dir_a_path. Returns its path, or None if they quit."""
    if paths.is_cloud_path(args.dir_a_path):
        tree = replicafactory.create_dirtree_from_arg(args.dir_a_path, args.max_depth)
        if tree is None:
            return None
        picked = picker.pick_from_tree(tree)
        return picked[0].full_filesystem_path() if picked else None

    # A local dir: treepicker scans it itself, which is much faster than building a DirTree
    replicafactory.validate_dir(args.dir_a_path)
    return picker.pick_under_dir(os.path.realpath(args.dir_a_path), args.max_depth)


def use_picked_path(path, execute=None):
    """Print the picked path, or replace this process with `execute path` if a program was given."""
    if execute is None:
        print(path)
    else:
        os.execvp(execute, [execute, path])
