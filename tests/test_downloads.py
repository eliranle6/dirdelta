import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import helpers  # noqa: F401 (its DOWNLOADS_DIR is a temp dir, patched again here)
from dirdelta import downloads


class DownloadsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        patcher = mock.patch('dirdelta.downloads.DOWNLOADS_DIR', os.path.join(self.tmpdir, 'downloads'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fetched = []

    def fetch(self, contents):
        def fetch(local_path):
            self.fetched.append(local_path)
            with open(local_path, 'w') as f:
                f.write(contents)
        return fetch

    def test_downloaded_once_under_its_name_in_a_dir_of_its_own(self):
        path = downloads.get('cloud/me/trip/beach.jpg', 5, self.fetch('beach'))
        self.assertEqual(os.path.basename(path), 'beach.jpg')
        self.assertEqual(os.listdir(os.path.dirname(path)), ['beach.jpg'])
        self.assertEqual(downloads.get('cloud/me/trip/beach.jpg', 5, self.fetch('other')), path)
        self.assertEqual(len(self.fetched), 1)
        with open(path) as f:
            self.assertEqual(f.read(), 'beach')
        # Of another size (changed), or another path: anew, elsewhere
        self.assertNotEqual(downloads.get('cloud/me/trip/beach.jpg', 6, self.fetch('beach!')), path)
        self.assertNotEqual(downloads.get('cloud/me/beach.jpg', 5, self.fetch('beach')), path)
        self.assertEqual(len(self.fetched), 3)

    def test_a_failed_download_keeps_nothing(self):
        def fail(local_path):
            open(local_path, 'w').close()
            raise OSError('cut off')
        with self.assertRaises(OSError):
            downloads.get('cloud/me/a.txt', 3, fail)
        self.assertEqual(os.listdir(downloads.DOWNLOADS_DIR), [])

    def test_the_least_recently_used_go_beyond_max_bytes(self):
        with mock.patch('dirdelta.downloads.MAX_BYTES', 10):
            first = downloads.get('cloud/1', 4, self.fetch('1111'))
            second = downloads.get('cloud/2', 4, self.fetch('2222'))
            # Used again: newer than the second
            past = time.time() - 100
            os.utime(os.path.dirname(first), (past, past))
            os.utime(os.path.dirname(second), (past + 1, past + 1))
            downloads.get('cloud/1', 4, self.fetch('1111'))
            third = downloads.get('cloud/3', 4, self.fetch('3333'))
        self.assertTrue(os.path.exists(first))
        self.assertFalse(os.path.exists(second))
        self.assertTrue(os.path.exists(third))


if __name__ == '__main__':
    unittest.main()
