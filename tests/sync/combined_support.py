"""The combined tree's tests' fixture: two local replicas, A and B, with files only in each and one that
differs"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.trees import localdiskdirtree


class ReplicasTest(unittest.TestCase):
    """Two local replicas, A and B"""
    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-combined-'))
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.path_a, self.path_b = os.path.join(self.tmpdir, 'A'), os.path.join(self.tmpdir, 'B')
        helpers.make_files(self.path_a, ['new/a.txt', 'gone.txt', 'both.txt'])
        helpers.make_files(self.path_b, ['b.txt', 'both.txt', 'old/b2.txt'])
        with open(os.path.join(self.path_b, 'both.txt'), 'w') as f:
            f.write("B's longer version")
        self.trash = helpers.fake_trash(self)
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'), mock.patch('dirdelta.ui.messages.print_progress'),
                        mock.patch('dirdelta.ui.messages.show')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.replica_a = localdiskdirtree.LocalDiskDirTree(self.path_a, silent=True)
        self.replica_b = localdiskdirtree.LocalDiskDirTree(self.path_b, silent=True)

    def read(self, root, relpath):
        with open(os.path.join(root, relpath)) as f:
            return f.read()
