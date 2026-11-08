"""Which drives have a trash for a local replica's removed files (fs.has_trash()): the home's, or one
with a trash dir already; the others' files are removed for good, no trash dir made there"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the caches' fakes)
from dirdelta.trees.localdiskdirtree import fs


class HasTrashTest(unittest.TestCase):
    def setUp(self):
        self.drive = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.drive)
        self.path = os.path.join(self.drive, 'a.txt')
        with open(self.path, 'w') as f:
            f.write('a')
        # Another drive's top: here, the temp dir
        patcher = mock.patch('dirdelta.trees.localdiskdirtree.fs._mount_point', return_value=self.drive)
        patcher.start()
        self.addCleanup(patcher.stop)

    def home_trash_on(self, path):
        patcher = mock.patch('dirdelta.trees.localdiskdirtree.fs._home_trash', return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_homes_drive_has_one(self):
        # (Not there yet: the closest dir there is on the same drive)
        self.home_trash_on(os.path.join(self.drive, 'home', '.local', 'share', 'Trash'))
        self.assertTrue(fs.has_trash(self.path))

    def test_another_drive_has_one_only_if_it_has_a_trash_dir_already(self):
        self.home_trash_on('/proc/no-such-trash')
        self.assertFalse(fs.has_trash(self.path))
        os.makedirs(os.path.join(self.drive, '.Trash-%d' % (os.getuid(),)))
        self.assertTrue(fs.has_trash(self.path))

    def test_a_trash_dir_of_another_users_isnt_one(self):
        # E.g. root's, on a Windows drive: gio refuses it
        self.home_trash_on('/proc/no-such-trash')
        os.makedirs(os.path.join(self.drive, '.Trash-%d' % (os.getuid(),)))
        real_stat = os.stat
        with mock.patch('os.stat', side_effect=lambda path, *args, **kwargs: mock.Mock(
                st_uid=0, st_dev=real_stat(path).st_dev, st_mode=real_stat(path).st_mode)):
            self.assertFalse(fs.has_trash(self.path))

    def test_without_one_a_file_is_removed_for_good_and_no_trash_dir_is_made(self):
        self.home_trash_on('/proc/no-such-trash')
        with mock.patch('subprocess.run') as run:
            self.assertFalse(fs.trash(self.path))
        run.assert_not_called()
        self.assertEqual(os.listdir(self.drive), [])
