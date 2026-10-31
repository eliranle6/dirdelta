"""Fakes shared by the dirdelta tests, for code that would otherwise run treepicker (dirdelta.picker)."""
import atexit
import os
import shutil
import tempfile
from unittest import mock

from dirdelta import downloads
from dirdelta import hashcache
from dirdelta import mounts
from dirdelta import picker

# The tests never keep hashes in the real hash cache (~/.cache/dirdelta/hashes.sqlite): every test
# module that hashes files imports this one, and unittest imports them all before running any
_hash_cache_dir = tempfile.mkdtemp(prefix='dirdelta-test-hashes-')
hashcache.CACHE_FILE = os.path.join(_hash_cache_dir, 'hashes.sqlite')
atexit.register(shutil.rmtree, _hash_cache_dir, ignore_errors=True)
# Nor read or write the real mounts' file (~/.config/dirdelta/mounts.json): the tests that may check
# replicas' mounts (choose_replicas') import this module
_mounts_dir = tempfile.mkdtemp(prefix='dirdelta-test-mounts-')
mounts.MOUNTS_FILE = os.path.join(_mounts_dir, 'mounts.json')
atexit.register(shutil.rmtree, _mounts_dir, ignore_errors=True)
# Nor download into the real downloads' cache (~/.cache/dirdelta/downloads): test_inbox and
# test_downloads import this module
_downloads_dir = tempfile.mkdtemp(prefix='dirdelta-test-downloads-')
downloads.DOWNLOADS_DIR = os.path.join(_downloads_dir, 'downloads')
atexit.register(shutil.rmtree, _downloads_dir, ignore_errors=True)


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
    given: a picker.Picked, or a list of the picked files (Enter on the root), or None (quitting)."""
    def pick_files(rootpath, relpaths, *_, **__):
        chosen = choose(relpaths)
        return picker.Picked('', '', chosen) if isinstance(chosen, list) else chosen
    return mock.patch('dirdelta.picker.pick_files', side_effect=pick_files)


def answering_option_picker(answers):
    """Patch picker.pick_option so each call returns the option that the next of answers is, or
    starts with (e.g. 'Copy' for "Copy the 2 files to ..."); None for quitting. Its calls are the
    mock's."""
    answers = list(answers)

    def pick_option(options, *_, **__):
        answer = answers.pop(0)
        if answer is None:
            return None
        return next(option for option in options if option == answer or option.startswith(answer))
    return mock.patch('dirdelta.picker.pick_option', side_effect=pick_option)


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
