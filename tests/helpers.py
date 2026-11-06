"""Fakes shared by the dirdelta tests, for code that would otherwise run treepicker (dirdelta.ui.picker)."""
import atexit
import os
import shutil
import tempfile
from unittest import mock

from dirdelta.util import downloads
from dirdelta.drive import drivecache
from dirdelta.hashes import hashcache
from dirdelta.known import mounts
from dirdelta.ui import picker
from dirdelta.known import replicas
from dirdelta.known import settings

# The tests never keep hashes in the real hash cache (~/.cache/dirdelta/hashes.sqlite): every test
# module that hashes files imports this one, and unittest imports them all before running any
_hash_cache_dir = tempfile.mkdtemp(prefix='dirdelta-test-hashes-')
hashcache.CACHE_FILE = os.path.join(_hash_cache_dir, 'hashes.sqlite')
atexit.register(shutil.rmtree, _hash_cache_dir, ignore_errors=True)
# Nor read, or import into, the real Drive cache (~/.cache/dirdelta): the tests that make its own patch
# it, but a Drive replica's identity asks it for the root's id
drivecache.names.LINES_FILE = os.path.join(_hash_cache_dir, 'dirdelta', 'files.txt')
# Nor read or write the real mounts' file (~/.config/dirdelta/mounts.json): the tests that may check
# replicas' mounts (choose_replicas') import this module
_mounts_dir = tempfile.mkdtemp(prefix='dirdelta-test-mounts-')
mounts.names.MOUNTS_FILE = os.path.join(_mounts_dir, 'mounts.json')
atexit.register(shutil.rmtree, _mounts_dir, ignore_errors=True)
# Nor go by the real labels (~/.config/dirdelta/replicas.json), which say what screens call a replica
replicas.REPLICAS_FILE = os.path.join(_mounts_dir, 'replicas.json')
# Nor read or write the real settings (~/.config/dirdelta/settings.json)
settings.SETTINGS_FILE = os.path.join(_mounts_dir, 'settings.json')
# Nor write the real errors' log (~/.cache/dirdelta/errors.log)
picker.updates.ERRORS_LOG = os.path.join(_hash_cache_dir, 'errors.log')
# Nor download into the real downloads' cache (~/.cache/dirdelta/downloads): test_inbox and
# test_downloads import this module
_downloads_dir = tempfile.mkdtemp(prefix='dirdelta-test-downloads-')
downloads.DOWNLOADS_DIR = os.path.join(_downloads_dir, 'downloads')
atexit.register(shutil.rmtree, _downloads_dir, ignore_errors=True)


def remove_drive_cache(path):
    """Remove the Drive cache that LINES_FILE was pointed at path for: its database, and its old
    file, imported or not"""
    database = os.path.splitext(path)[0] + '.sqlite'
    drivecache.close()
    for file in (path, path + '.bak', database, database + '-wal', database + '-shm'):
        if os.path.exists(file):
            os.remove(file)


def answer_of(options, answer):
    """What picker.pick_option() returns of options when answer, a label (or, for a test that knows
    it, an option's id), is picked: the option with that label, or else one starting with it; answer
    itself if there's none"""
    choices = [option for option in options if not isinstance(option, picker.Skipped)]
    for matches in (lambda option: picker.option_id(option) == answer,
                    lambda option: picker.option_label(option) == answer,
                    lambda option: isinstance(answer, str) and picker.option_label(option).startswith(answer)):
        for option in choices:
            if matches(option):
                return picker.option_id(option)
    return answer


def labels_of(options):
    """options (a pick_option()'s) as labels, without its blank lines"""
    return [picker.option_label(option) for option in options if option != picker.BLANK]


def shown_of(options):
    """{label: how it's shown at first} of options (a pick_option()'s)"""
    return {picker.option_label(option): (option if isinstance(option, picker.Skipped) else
                                          option.shown if isinstance(option, picker.Option) and option.shown is not None
                                          else picker.option_label(option))
            for option in options if option != picker.BLANK}


def scripted_option_picker(answers):
    """Patch picker.pick_option so each call returns the option of the next of the given labels."""
    answers = list(answers)
    return mock.patch('dirdelta.ui.picker.pick_option',
                      side_effect=lambda options, *_, **__: answer_of(options, answers.pop(0)))


def scripted_tree_picker(choose):
    """Patch picker.pick_from_tree so it returns choose(tree), called with the tree it was given."""
    return mock.patch('dirdelta.ui.picker.pick_from_tree',
                      side_effect=lambda tree, *_, **__: choose(tree))


def scripted_files_picker(choose):
    """Patch picker.pick_files so it returns choose(relpaths), called with the relpaths it was
    given: a picker.Picked, or a list of the picked files (Enter on the root), or None (quitting)."""
    def pick_files(rootpath, relpaths, *_, **__):
        chosen = choose(relpaths)
        return picker.Picked('', '', chosen) if isinstance(chosen, list) else chosen
    return mock.patch('dirdelta.ui.picker.pick_files', side_effect=pick_files)


def answering_option_picker(answers):
    """Patch picker.pick_option so each call returns the option that the next of answers is, or
    starts with (e.g. 'Copy' for "Copy the 2 files to ..."); None for quitting. Its calls are the
    mock's."""
    answers = list(answers)

    def pick_option(options, *_, **__):
        answer = answers.pop(0)
        return None if answer is None else answer_of(options, answer)
    return mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option)


def scripted_dir_picker(picked_path):
    """Patch picker.pick_under_dir so it returns picked_path."""
    return mock.patch('dirdelta.ui.picker.pick_under_dir', return_value=picked_path)


def all_files(tree):
    return sorted(tree.iter_files(), key=lambda entry: entry.relpath)


def make_files(root, relpaths):
    for relpath in relpaths:
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(relpath)


def fake_trash(test):
    """Patch the desktop's trash (gio trash, see localdiskdirtree._trash()) for the test: a trashed
    file is moved into a temp dir (returned) instead, by its name"""
    trash_dir = tempfile.mkdtemp(prefix='dirdelta-test-trash-')
    test.addCleanup(shutil.rmtree, trash_dir, ignore_errors=True)

    def trash(path):
        shutil.move(path, os.path.join(trash_dir, os.path.basename(path)))
    patcher = mock.patch('dirdelta.trees.localdiskdirtree.fs._trash', side_effect=trash)
    patcher.start()
    test.addCleanup(patcher.stop)
    return trash_dir
