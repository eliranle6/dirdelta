"""Fakes shared by the dirdelta tests, for code that would otherwise block on a curses picker."""
import os
from unittest import mock


def scripted_option_picker(answers):
    """Patch OptionPickerByMenuTraverse so each pick_one() returns the next of the given labels."""
    answers = list(answers)
    picker_class = mock.Mock()
    picker_class.return_value.pick_one.side_effect = lambda: answers.pop(0)
    return mock.patch('treepicker.optionpicker.OptionPickerByMenuTraverse', picker_class)


def scripted_tree_picker(choose):
    """Patch TreePicker so pick() returns choose(tree), called with the tree the picker was given."""
    def make_picker(tree, *args, **kwargs):
        picker = mock.Mock()
        picker.pick.side_effect = lambda: choose(tree)
        picker.pick_one.side_effect = lambda: choose(tree)
        return picker
    return mock.patch('treepicker.TreePicker', side_effect=make_picker)


def all_files(tree):
    return sorted(tree.iter_files(), key=lambda entry: entry.relpath)


def make_files(root, relpaths):
    for relpath in relpaths:
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(relpath)
