import os

import treepicker
import utils


def run(args):
    """Let the user pick a file or dir under args.dir_a_path. Returns its path, or None if they quit."""
    picker = FilesystemPicker(args.dir_a_path, args.max_depth)
    picked = picker.pick_one()
    return picked[0].full_filesystem_path() if picked else None


def use_picked_path(path, execute=None):
    """Print the picked path, or replace this process with `execute path` if a program was given."""
    if execute is None:
        print(path)
    else:
        os.execvp(execute, [execute, path])


class FilesystemPicker(object):
    def __init__(self, rootpath, max_depth=None):
        dirtree = utils.create_dirtree_from_arg(rootpath, max_depth)
        self._tree_picker = treepicker.TreePicker(dirtree, min_nr_options=1, max_nr_options=1)

    def pick_one(self):
        return self._tree_picker.pick_one()
