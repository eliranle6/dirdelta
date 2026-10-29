import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import hashcache


class HashCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='dirdelta-hashcache-')
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.cache = os.path.join(self.tmpdir, 'cache', 'hashes.json')
        for patcher in (mock.patch('dirdelta.hashcache.CACHE_FILE', self.cache),
                        mock.patch('dirdelta.hashcache._cache', None),
                        mock.patch('dirdelta.hashcache._is_dirty', False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.path = os.path.join(self.tmpdir, 'x')
        with open(self.path, 'w') as f:
            f.write('x')

    def test_a_hash_is_kept_until_the_file_changes(self):
        hashcache.put(self.path, {'sha1': 'H'})
        self.assertEqual(hashcache.get(self.path, 'sha1'), 'H')
        self.assertIsNone(hashcache.get(self.path, 'sha256'))
        with open(self.path, 'w') as f:
            f.write('changed')
        self.assertIsNone(hashcache.get(self.path, 'sha1'))

    def test_its_saved_and_read_back(self):
        hashcache.put(self.path, {'sha1': 'H'})
        hashcache.save()
        with open(self.cache) as f:
            self.assertEqual(json.load(f)[self.path]['hashes'], {'sha1': 'H'})
        with mock.patch('dirdelta.hashcache._cache', None):
            self.assertEqual(hashcache.get(self.path, 'sha1'), 'H')

    def test_a_gone_file_has_none(self):
        self.assertIsNone(hashcache.get(os.path.join(self.tmpdir, 'nope'), 'sha1'))
        hashcache.put(os.path.join(self.tmpdir, 'nope'), {'sha1': 'H'})
        self.assertIsNone(hashcache.get(os.path.join(self.tmpdir, 'nope'), 'sha1'))


if __name__ == '__main__':
    unittest.main()
