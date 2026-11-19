"""Reading the Drive replicas' lists again when dirdelta is opened, once over a day old (freshening.py)"""
import datetime
import tempfile
import threading
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real caches and config aren't touched)
from dirdelta.drive import freshening


class FresheningTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 11, 19, 12, 0)
        self.times = {'cloud/old': self.now - datetime.timedelta(days=2), 'cloud/new': self.now - datetime.timedelta(hours=3),
                      'cloud/never': None}
        self.read = []
        self.done = threading.Event()
        token = tempfile.NamedTemporaryFile()
        self.addCleanup(token.close)
        for patcher in (mock.patch('dirdelta.known.replicainfo.cache_time', side_effect=self.times.get),
                        mock.patch('dirdelta.drive.driveapi.TOKEN_PATH', token.name),
                        mock.patch('dirdelta.drive.driveapi.can_log_in_quietly', return_value=True),
                        mock.patch('dirdelta.drive.clouddirtree.refresh.refresh_cache', side_effect=self._refresh)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _refresh(self, folder):
        self.read.append(folder)
        if len(self.read) == 2:
            self.done.set()

    def test_the_lists_over_a_day_old_or_never_read_are_read_again_and_the_rest_and_local_ones_arent(self):
        with mock.patch('dirdelta.drive.freshening.datetime') as fake:
            fake.datetime.now.return_value = self.now
            fake.timedelta = datetime.timedelta
            found = freshening.refresh_stale(['/home/me/tree', 'cloud/old', 'cloud/new', 'cloud/never', 'cloud/old'])
        self.assertEqual(['cloud/old', 'cloud/never'], found)
        self.assertTrue(self.done.wait(5))
        self.assertEqual(['/old', '/never'], self.read)

    def test_nothing_is_read_without_a_drive_login(self):
        with mock.patch('dirdelta.drive.driveapi.TOKEN_PATH', '/nonexistent/token.json'):
            self.assertEqual([], freshening.refresh_stale(['cloud/old']))


if __name__ == '__main__':
    unittest.main()
