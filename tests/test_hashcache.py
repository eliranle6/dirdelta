import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import hashcache


class HashCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='dirdelta-hashcache-')
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.cache = os.path.join(self.tmpdir, 'cache', 'hashes.sqlite')
        # A database of its own (opened again, as CACHE_FILE changed), and back to the tests' one
        patcher = mock.patch('dirdelta.hashcache.CACHE_FILE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.make('x', 'x')

    def make(self, relpath, contents):
        path = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(contents)
        return path

    def test_a_hash_is_kept_until_the_file_changes(self):
        hashcache.put(self.path, {'sha1': 'H'})
        self.assertEqual(hashcache.get(self.path, 'sha1'), 'H')
        self.assertIsNone(hashcache.get(self.path, 'sha256'))
        with open(self.path, 'w') as f:
            f.write('changed')
        self.assertIsNone(hashcache.get(self.path, 'sha1'))

    def test_a_files_hashes_are_kept_together(self):
        hashcache.put(self.path, {'sha1': 'H'})
        hashcache.put(self.path, {'sha256': 'S'})
        self.assertEqual(hashcache.get_all(self.path), {'sha1': 'H', 'sha256': 'S'})

    def test_its_committed_and_read_back(self):
        hashcache.put(self.path, {'sha1': 'H'})
        hashcache.save()
        with sqlite3.connect(self.cache) as db:
            self.assertEqual(db.execute('SELECT path, hashes FROM files').fetchall(),
                             [(self.path, '{"sha1": "H"}')])

    def test_a_gone_file_has_none(self):
        self.assertIsNone(hashcache.get(os.path.join(self.tmpdir, 'nope'), 'sha1'))
        hashcache.put(os.path.join(self.tmpdir, 'nope'), {'sha1': 'H'})
        self.assertIsNone(hashcache.get(os.path.join(self.tmpdir, 'nope'), 'sha1'))

    def test_a_stamp_given_is_what_it_was_when_read(self):
        stat = os.stat(self.path)
        hashcache.put(self.path, {'sha1': 'H'}, [stat.st_size, stat.st_mtime_ns - 1])
        # It changed since it was read
        self.assertIsNone(hashcache.get(self.path, 'sha1'))

    def test_the_files_under_a_dir(self):
        under = self.make('d/a/y', 'yy')
        hashcache.put(under, {'sha1': 'Y'})
        hashcache.put(self.make('d2/z', 'z'), {'sha1': 'Z'})
        hashcache.put(self.path, {'sha1': 'H'})
        stat = os.stat(under)
        self.assertEqual(hashcache.known_under(os.path.join(self.tmpdir, 'd')),
                         {'a/y': (stat.st_size, stat.st_mtime_ns, {'sha1': 'Y'})})

    def test_a_moved_file_or_dir_keeps_its_hashes(self):
        hashcache.put(self.path, {'sha1': 'H'})
        hashcache.put(self.make('d/a/y', 'yy'), {'sha1': 'Y'})
        hashcache.put(self.make('d2/z', 'z'), {'sha1': 'Z'})
        os.rename(self.path, os.path.join(self.tmpdir, 'x2'))
        hashcache.move(self.path, os.path.join(self.tmpdir, 'x2'))
        os.rename(os.path.join(self.tmpdir, 'd'), os.path.join(self.tmpdir, 'e'))
        hashcache.move(os.path.join(self.tmpdir, 'd'), os.path.join(self.tmpdir, 'e'))
        self.assertEqual(hashcache.get(os.path.join(self.tmpdir, 'x2'), 'sha1'), 'H')
        self.assertEqual(hashcache.get(os.path.join(self.tmpdir, 'e', 'a', 'y'), 'sha1'), 'Y')
        # Not d2, which only starts like d
        self.assertEqual(hashcache.get(os.path.join(self.tmpdir, 'd2', 'z'), 'sha1'), 'Z')


if __name__ == '__main__':
    unittest.main()
