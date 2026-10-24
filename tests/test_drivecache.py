import json
import os
import tempfile
import unittest
from unittest import mock

from dirdelta import drivecache
from test_clouddirtree import ITEMS


class EntriesTest(unittest.TestCase):
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-drive-cache-')
        with os.fdopen(fd, 'w') as f:
            f.write('not a JSON line, skipped\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        patcher = mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.remove, self.cache)

    def test_entries_under_a_folder(self):
        entries = list(drivecache.entries('/mein'))
        self.assertEqual(sorted(entries), sorted([
            ('song.mp3', 'song', False),
            ('album', 'album', True),
            ('album/track.mp3', 'track', False),
            ('dup.mp3', 'dup1', False),
            ('dup.mp3', 'dup2', False),
        ]))

    def test_each_folder_comes_before_whats_in_it(self):
        relpaths = [relpath for relpath, _, _ in drivecache.entries('/mein')]
        self.assertLess(relpaths.index('album'), relpaths.index('album/track.mp3'))
