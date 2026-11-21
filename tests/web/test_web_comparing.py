"""Comparing a pair again in the background (web/comparing.py): both file lists read anew, and what each lacks noted
as the pair's comparison, nothing changed in the replicas"""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import helpers
from dirdelta.known import replicas
from dirdelta.known import users
from dirdelta.web import comparing


class ComparingTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.a, self.b = os.path.join(self.tmpdir, 'a'), os.path.join(self.tmpdir, 'b')
        helpers.make_files(self.a, ['both.txt', 'only-a/1.txt', 'only-a/2.txt'])
        helpers.make_files(self.b, ['both.txt', 'only-b.txt'])
        patcher = mock.patch('dirdelta.known.replicas.REPLICAS_FILE', os.path.join(self.tmpdir, 'replicas.json'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def wait(self):
        for _ in range(500):
            if not any(one['doing'] for one in comparing.state(users.OWNER)):
                return
            time.sleep(0.01)
        self.fail("still comparing")

    def test_a_pair_compared_again_has_its_counts_noted(self):
        comparing.start(users.OWNER, [(self.a, self.b)])
        self.wait()
        found = replicas.load().comparison(self.a, self.b)
        self.assertEqual(([2, 1], [3, 2]), (found['only'], found['total']))
        self.assertEqual(['both.txt', 'only-b.txt'], sorted(os.listdir(self.b)))

    def test_one_whose_disk_isnt_there_says_so(self):
        comparing.start(users.OWNER, [(self.a, os.path.join(self.tmpdir, 'gone'))])
        self.wait()
        self.assertEqual(["its disk isn't mounted"], [one['error'] for one in comparing.state(users.OWNER)])


if __name__ == '__main__':
    unittest.main()
