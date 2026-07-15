import argparse
import os

import clouddirtree
import cursesswitch
import localdiskdirtree
import treepicker
import utils


def run(args):
    picker = FilesystemPicker(args.dir_a_path)
    picked_file = picker.pick_one()
    if picked_file is not None:
        if args.execute is not None:
            command = [os.path.basename(args.execute), picked_file.full_filesystem_path()]
            os.execve(args.execute, command, {})
        elif picked_file:
            picked_file = picked_file[0]
            cursesswitch.print_line(picked_file.full_filesystem_path())


class FilesystemPicker(object):
    def __init__(self, rootpath):
        dirtree = utils.create_dirtree_from_arg(rootpath)
        self._tree_picker = treepicker.TreePicker(dirtree, min_nr_options=1, max_nr_options=1)

    def pick_one(self):
        return self._tree_picker.pick_one()
