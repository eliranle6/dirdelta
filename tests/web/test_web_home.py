"""The web version's dashboard and Sync page (web/home.py), and the flows they start (daemon.flow())"""
import datetime
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from dirdelta.known import replicalog
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
        self.assertEqual({self.local, 'cloud/photos', self.gone}, set(found))
        self.assertTrue(found[self.local]['there'])
        self.assertEqual(('local', 'drive'), (found[self.local]['kind'], found['cloud/photos']['kind']))
        self.assertFalse(found[self.gone]['there'])
        self.assertEqual('not there', found[self.gone]['why'])

    def test_every_two_replicas_are_a_pair_and_the_inboxes_are_apart(self):
        found = self.call('GET', '/api/home')
        self.assertEqual({frozenset((self.local, 'cloud/photos')), frozenset((self.gone, self.local)), frozenset((self.gone, 'cloud/photos'))},
                         {frozenset((pair['a'], pair['b'])) for pair in found['pairs']})
        inbox = next(inbox for inbox in found['inboxes'] if inbox['path'] == 'cloud/unsorted')
        self.assertEqual(('drive', self.local), (inbox['kind'], inbox['dests'][0]['path']))

    def test_a_pairs_status_says_how_much_was_in_step_and_whether_its_changed_since(self):
        known = replicas.load()
        known.note_compared(self.local, 'cloud/photos', 10, 30, datetime.datetime(2026, 11, 1, 9, 0), totals=[1000, 1020])
        known.note_seen(replicalog.identity(self.local), self.local, None, datetime.datetime(2026, 11, 2, 9, 0))
        known.note_changed(replicalog.identity(self.local), datetime.datetime(2026, 11, 2, 9, 0))
        pair = next(pair for pair in self.call('GET', '/api/home')['pairs'] if pair['b'] == 'cloud/photos')
        self.assertEqual((10, 30, 1000), (pair['synced']['onlyA'], pair['synced']['onlyB'], pair['synced']['totalA']))
        self.assertAlmostEqual(990 / 1030, pair['synced']['share'])
        self.assertEqual('2026-11-01 09:00', pair['state']['when'])
        self.assertEqual(1, len(pair['changedSince']))

    def test_while_a_pairs_sync_runs_the_dashboard_says_which_pair_it_is(self):
        self.assertIsNone(self.call('GET', '/api/home')['running'])
        release = threading.Event()
        self.addCleanup(release.set)
        asked = {'kind': 'pair', 'a': self.local, 'b': 'cloud/photos'}
        self.session.start(lambda: release.wait(5), 'replicas', asked)
        self.assertEqual(asked, self.call('GET', '/api/home')['running']['what'])

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
