"""The web version's dashboard and Sync page (web/home.py), and the flows they start (daemon.flow())"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta.known import replicas
from dirdelta.web import daemon, home
from web_support import WebTest


class HomeTest(WebTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.local = os.path.join(self.temp, 'photos')
        os.makedirs(self.local)
        self.gone = os.path.join(self.temp, 'gone')
        known = replicas.Replicas(history=[(self.local, 'cloud/photos'), (self.gone, self.local)],
                                  favorites=[(self.local, 'cloud/photos')], sorts=[('cloud/unsorted', self.local)])
        patcher = mock.patch('dirdelta.known.replicas.load', return_value=known)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.routes = home.routes(self.session)

    def call(self, method, path, body=None):
        return self.routes[(method, path)]({}, body or {})

    def test_the_dashboard_has_each_replica_once_and_says_which_arent_there(self):
        found = {replica['path']: replica for replica in self.call('GET', '/api/home')['replicas']}
        self.assertEqual({self.local, 'cloud/photos', self.gone, 'cloud/unsorted'}, set(found))
        self.assertTrue(found[self.local]['there'])
        self.assertEqual(('local', 'drive'), (found[self.local]['kind'], found['cloud/photos']['kind']))
        self.assertFalse(found[self.gone]['there'])
        self.assertEqual('not there', found[self.gone]['why'])

    def test_the_sync_page_has_the_favorites_the_other_recent_pairs_and_the_sorts(self):
        found = self.call('GET', '/api/sync')
        self.assertEqual([(self.local, 'cloud/photos')], [(pair['a'], pair['b']) for pair in found['favorites']])
        self.assertEqual([(self.gone, self.local)], [(pair['a'], pair['b']) for pair in found['recent']])
        self.assertEqual([('cloud/unsorted', self.local)], [(sort['inbox'], sort['root']) for sort in found['sorts']])

    def test_only_a_known_local_replica_is_hashed_from_the_dashboard(self):
        with mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.start_hashing') as start_hashing:
            self.assertFalse(self.call('POST', '/api/home/hash', {'path': '/etc'})['ok'])
            self.assertFalse(self.call('POST', '/api/home/hash', {'path': 'cloud/photos'})['ok'])
            self.assertTrue(self.call('POST', '/api/home/hash', {'path': self.local})['ok'])
        start_hashing.assert_called_once_with(self.local)


class FlowTest(unittest.TestCase):
    def test_a_pair_is_synced_a_sort_sorted_and_else_the_start_menu_shown(self):
        with mock.patch('dirdelta.main.run_pair') as run_pair, mock.patch('dirdelta.main.run_sort') as run_sort, \
                mock.patch('dirdelta.main.start_menu') as start_menu:
            daemon.flow({'kind': 'pair', 'a': '/a', 'b': 'cloud/b'})
            daemon.flow({'kind': 'sort', 'inbox': 'cloud/in', 'root': '/r'})
            daemon.flow({})
        run_pair.assert_called_once_with('/a', 'cloud/b')
        run_sort.assert_called_once_with('cloud/in', '/r')
        start_menu.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
