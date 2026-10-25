"""Fakes shared by the dirdelta tests, for code that would otherwise run treepick (dirdelta.picker)."""
import os
from unittest import mock


def scripted_option_picker(answers):
    """Patch picker.pick_option so each call returns the next of the given labels."""
    answers = list(answers)
    return mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0))


def scripted_tree_picker(choose):
    """Patch picker.pick_from_tree so it returns choose(tree), called with the tree it was given."""
    return mock.patch('dirdelta.picker.pick_from_tree',
                      side_effect=lambda tree, *_, **__: choose(tree))


def scripted_files_picker(choose):
    """Patch picker.pick_files so it returns choose(relpaths), called with the relpaths it was
    given."""
    return mock.patch('dirdelta.picker.pick_files',
                      side_effect=lambda rootpath, relpaths, *_, **__: choose(relpaths))


def scripted_dir_picker(picked_path):
    """Patch picker.pick_under_dir so it returns picked_path."""
    return mock.patch('dirdelta.picker.pick_under_dir', return_value=picked_path)


def all_files(tree):
    return sorted(tree.iter_files(), key=lambda entry: entry.relpath)


def make_files(root, relpaths):
    for relpath in relpaths:
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(relpath)
