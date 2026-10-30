import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import replicas


class ReplicasTest(unittest.TestCase):
    def test_a_recorded_pair_is_the_latest(self):
        known = replicas.Replicas()
        known.record('/a', 'cloud/b')
        known.record('/c', '/d')
        self.assertEqual(known.history, [('/c', '/d'), ('/a', 'cloud/b')])

    def test_a_pair_used_again_moves_to_the_top_once(self):
        known = replicas.Replicas()
        for pair in [('/a', '/b'), ('/c', '/d'), ('/a', '/b')]:
            known.record(*pair)
        self.assertEqual(known.history, [('/a', '/b'), ('/c', '/d')])

    def test_a_pair_is_the_same_either_way_around(self):
        known = replicas.Replicas()
        known.record('/a', '/b')
        known.record('/b', '/a')
        # Kept the way around it was last used
        self.assertEqual(known.history, [('/b', '/a')])

    def test_paths_are_normalized(self):
        known = replicas.Replicas()
        known.record('/a/', 'cloud//b/')
        known.record('/a', 'cloud/b')
        self.assertEqual(known.history, [('/a', 'cloud/b')])
        with mock.patch('os.getcwd', return_value='/home/me'):
            self.assertEqual(replicas.normalized('dir/sub'), '/home/me/dir/sub')

    def test_history_is_capped(self):
        known = replicas.Replicas()
        for i in range(replicas.MAX_HISTORY + 5):
            known.record('/a%d' % (i,), '/b')
        self.assertEqual(len(known.history), replicas.MAX_HISTORY)
        self.assertEqual(known.history[0], ('/a%d' % (replicas.MAX_HISTORY + 4,), '/b'))

    def test_toggle_favorite(self):
        known = replicas.Replicas()
        self.assertFalse(known.is_favorite('/a', '/b'))
        known.toggle_favorite('/a', '/b')
        self.assertTrue(known.is_favorite('/b', '/a'))
        self.assertEqual(known.favorites, [('/a', '/b')])
        known.toggle_favorite('/b/', '/a')
        self.assertFalse(known.is_favorite('/a', '/b'))
        self.assertEqual(known.favorites, [])

    def test_recent_leaves_out_the_favorites(self):
        known = replicas.Replicas()
        known.record('/a', '/b')
        known.record('/c', '/d')
        known.toggle_favorite('/b', '/a')
        self.assertEqual(known.recent(), [('/c', '/d')])


class ReplicasFileTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Registered first, so it runs after the other cleanups
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.path = os.path.join(self.tmpdir, 'config', 'dirdelta', 'replicas.json')
        patcher = mock.patch('dirdelta.replicas.REPLICAS_FILE', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, content):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w') as f:
            f.write(content)

    def test_no_file_is_no_replicas(self):
        known = replicas.load()
        self.assertEqual((known.history, known.favorites), ([], []))

    def test_saved_replicas_load_back(self):
        known = replicas.Replicas()
        known.record('/a', 'cloud/b')
        known.toggle_favorite('/mnt/win', 'cloud/me')
        known.record_sort('cloud/unsorted', 'cloud/me')
        known.record_dir('cloud/me/', 'photos/2026')
        # Its dir is made
        replicas.save(known)
        loaded = replicas.load()
        self.assertEqual(loaded.history, [('/a', 'cloud/b')])
        self.assertEqual(loaded.favorites, [('/mnt/win', 'cloud/me')])
        self.assertEqual(loaded.sorts, [('cloud/unsorted', 'cloud/me')])
        self.assertEqual(loaded.dirs_of('cloud/me'), ['photos/2026'])
        with open(self.path) as f:
            self.assertEqual(json.load(f), {'favorites': [['/mnt/win', 'cloud/me']],
                                            'history': [['/a', 'cloud/b']],
                                            'sorts': [['cloud/unsorted', 'cloud/me']],
                                            'recent_dirs': {'cloud/me': ['photos/2026']}})

    def test_a_sorted_trees_recent_dirs_the_latest_first_once_and_capped(self):
        known = replicas.Replicas()
        for relpath in ['a', 'b', 'a', '']:
            known.record_dir('/sorted', relpath)
        known.record_dir('/other', 'c')
        self.assertEqual(known.dirs_of('/sorted/'), ['', 'a', 'b'])
        self.assertEqual(known.dirs_of('/none'), [])
        for number in range(replicas.MAX_RECENT_DIRS + 1):
            known.record_dir('/sorted', str(number))
        self.assertEqual(len(known.dirs_of('/sorted')), replicas.MAX_RECENT_DIRS)

    def test_sorts_are_kept_the_latest_first_and_by_their_way_around(self):
        known = replicas.Replicas()
        known.record_sort('/in', '/sorted')
        known.record_sort('/other', '/sorted')
        known.record_sort('/in', '/sorted')
        known.record_sort('/sorted', '/in')
        self.assertEqual(known.sorts, [('/sorted', '/in'), ('/in', '/sorted'), ('/other', '/sorted')])
        for i in range(replicas.MAX_SORTS + 2):
            known.record_sort('/in%d' % (i,), '/sorted')
        self.assertEqual(len(known.sorts), replicas.MAX_SORTS)

    def test_a_file_from_before_sorts_has_none(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w') as f:
            json.dump({'history': [], 'favorites': []}, f)
        self.assertEqual(replicas.load().sorts, [])
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ['replicas.json'])

    def test_hand_edited_paths_are_normalized(self):
        self.write('{"favorites": [["/mnt/win/", "cloud//me"]]}')
        self.assertEqual(replicas.load().favorites, [('/mnt/win', 'cloud/me')])

    def test_a_broken_file_is_an_error_and_is_kept(self):
        for content in ['{"favorites": [["/a"]]}', 'not json', '[]', '{"history": [[1, 2]]}']:
            self.write(content)
            with self.assertRaises(replicas.ReplicasError) as raised:
                replicas.load()
            self.assertIn(self.path, str(raised.exception))
            with open(self.path) as f:
                self.assertEqual(f.read(), content)

    def test_an_unwritable_file_is_an_error(self):
        self.write('{}')
        os.chmod(os.path.dirname(self.path), 0o500)
        self.addCleanup(os.chmod, os.path.dirname(self.path), 0o700)
        if os.access(os.path.dirname(self.path), os.W_OK):
            self.skipTest("root can write anywhere")
        with self.assertRaises(replicas.ReplicasError):
            replicas.save(replicas.Replicas())


if __name__ == '__main__':
    unittest.main()
