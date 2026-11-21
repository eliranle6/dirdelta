"""The web version's dashboard and Sync page (web/home.py), and the flows they start (daemon.flow())"""
import datetime
import io
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from dirdelta.known import replicalog
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.ui import frontend
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.web import api, daemon, home
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

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.assertLess(time.monotonic(), deadline, "It didn't happen")
            time.sleep(0.01)

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

    def test_totals_that_cant_be_arent_taken_for_a_share(self):
        # (A local replica's were noted as none, beside files apart, before 2026-11-21: -100% in step)
        known = replicas.load()
        known.note_compared(self.local, 'cloud/photos', 3, 3, datetime.datetime(2026, 11, 1, 9, 0), totals=[0, 0])
        pair = next(pair for pair in self.call('GET', '/api/home')['pairs'] if pair['b'] == 'cloud/photos')
        self.assertEqual((3, 3, None), (pair['synced']['onlyA'], pair['synced']['onlyB'], pair['synced']['share']))

    def test_while_a_pairs_sync_runs_the_dashboard_says_which_pair_it_is(self):
        self.assertIsNone(self.call('GET', '/api/home')['running'])
        release = threading.Event()
        self.addCleanup(release.set)
        asked = {'kind': 'pair', 'a': self.local, 'b': 'cloud/photos'}
        self.session.start(lambda: release.wait(5), 'replicas', asked)
        self.assertEqual(asked, self.call('GET', '/api/home')['running']['what'])

    def test_the_mode_switches_to_live_and_back_while_nothing_runs(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.assertEqual(['LIVE', 'red'], self.call('POST', '/api/mode', {'live': True})['label'])
            self.assertEqual(['DRY RUN', 'green'], self.call('POST', '/api/mode', {'live': False})['label'])

    def test_the_mode_stays_while_files_are_being_changed(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def working():
            with messages.progress_screen("Copying", dryrun.label()):
                release.wait(5)
        self.session.start(working, 'replicas', {'kind': 'pair'})
        self.wait_for(lambda: self.session.screen() is not None)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.assertFalse(self.call('POST', '/api/mode', {'live': True})['ok'])
            self.assertEqual(['DRY RUN', 'green'], self.call('GET', '/api/home')['label'])

    def test_switched_to_live_in_the_middle_of_a_sync_its_screen_says_so_and_its_question_is_asked_again(self):
        answers = []
        self.session.start(lambda: answers.append(picker.pick_option(
            ["No", "Yes, do it"], header="Do this?\n" + dryrun.NOTE, label=('SYNC', 'blue'))), 'replicas', {'kind': 'pair'})
        self.wait_for(lambda: self.session.screen() is not None)
        asked = self.session.screen()
        state = api.routes(self.session, None)[('GET', '/api/state')]
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.assertTrue(self.call('POST', '/api/mode', {'live': True})['ok'])
            self.assertIn(['LIVE', 'red'], state({}, {})['screen']['labels'])
            asked.select("Yes, do it")
            asked.enter()
            self.wait_for(lambda: self.session.screen() not in (None, asked))
            again = self.session.screen()
            self.assertTrue(again.spec.header.startswith(picker.menus.SWITCHED_TO_LIVE))
            self.assertNotIn(dryrun.NOTE, again.spec.header)
            self.assertEqual([], answers)
            again.select("Yes, do it")
            again.enter()
            self.wait_for(lambda: answers)
        self.assertEqual(["Yes, do it"], answers)

    def test_a_syncs_tree_of_states_says_its_two_replicas_with_their_looks(self):
        known = replicas.load()
        known.set_look(replicanames.label_key('cloud/photos'), 'teal', None)
        self.session.start(lambda: picker.pick_states('photos ⇄ Drive', [picker.StateEntry('a.jpg', 'only-a')],
                                                      [picker.State('skip', ' ', 'grey'), picker.State('to-b', '⇒', 'blue', '>')]),
                           'replicas', {'kind': 'pair'})
        # (Said by the flow, once it's started: starting one forgets the last one's)
        frontend.show_replicas([(self.local, 'photos'), ('cloud/photos', 'Drive')])
        self.wait_for(lambda: self.session.screen() is not None)
        shown = api.routes(self.session, None)[('GET', '/api/state')]({}, {})['screen']['replicas']
        self.assertEqual([('photos', False), ('Drive', True)], [(replica['name'], replica['drive']) for replica in shown])
        self.assertEqual({'color': 'teal'}, shown[1]['look'])
        self.session.screen().cancel()

    def test_a_folders_photos_grid_gets_each_ones_picture_as_a_jpeg(self):
        from PIL import Image
        from dirdelta.ui import images
        made = lambda relpath, width, height: images.encoded(Image.new('RGB', (400, 300), (255, 0, 0)), width, height)
        self.session.start(lambda: picker.pick_files('photos', ['trip/a.jpg'], previews=lambda send: None, images=made),
                           'replicas', {'kind': 'pair'})
        self.wait_for(lambda: self.session.screen() is not None)
        routes = api.routes(self.session, None)
        screen = self.session.screen()
        self.assertTrue(routes[('GET', '/api/state')]({}, {})['screen']['hasPictures'])
        reply = routes[('GET', '/api/picture')]({'screen': str(screen.id), 'path': 'trip/a.jpg', 'size': '100'}, {})
        self.assertEqual('image/jpeg', reply.content_type)
        with Image.open(io.BytesIO(reply.data)) as picture:
            self.assertEqual((100, 75), picture.size)
        screen.cancel()

    def test_a_replica_is_named_and_unnamed_from_its_card(self):
        with mock.patch('dirdelta.known.replicas.save') as save:
            self.assertTrue(self.call('POST', '/api/replicas/name', {'path': 'cloud/photos', 'name': ' desktop '})['ok'])
            self.assertIn('desktop', replicas.load().labels.values())
            self.call('POST', '/api/replicas/name', {'path': 'cloud/photos', 'name': ''})
            self.assertNotIn('desktop', replicas.load().labels.values())
            self.assertFalse(self.call('POST', '/api/replicas/name', {'path': '/etc', 'name': 'x'})['ok'])
            # Its look, given with it, is on the dashboard: a Drive one's icon is always the cloud's, none kept
            self.call('POST', '/api/replicas/name', {'path': 'cloud/photos', 'name': 'desktop', 'color': 'teal', 'icon': 'nas'})
            found = next(replica for replica in self.call('GET', '/api/home')['replicas'] if replica['path'] == 'cloud/photos')
            self.assertEqual(found['look'], {'color': 'teal'})
        self.assertTrue(save.called)

    def test_a_main_replica_pairs_each_other_with_it_and_a_pair_can_be_added(self):
        with mock.patch('dirdelta.known.replicas.save'):
            self.assertTrue(self.call('POST', '/api/replicas/main', {'path': 'cloud/photos'})['ok'])
            found = self.call('GET', '/api/home')
            self.assertEqual({(pair['a'], pair['b']) for pair in found['pairs']},
                             {('cloud/photos', self.local), ('cloud/photos', self.gone)})
            self.assertEqual([replica['path'] for replica in found['replicas'] if replica['isMain']], ['cloud/photos'])
            self.assertTrue(self.call('POST', '/api/pairs/add', {'a': self.local, 'b': self.gone})['ok'])
            extra = [pair for pair in self.call('GET', '/api/home')['pairs'] if pair['extra']]
            self.assertEqual([(pair['a'], pair['b']) for pair in extra], [(self.local, self.gone)])
            self.assertFalse(self.call('POST', '/api/pairs/add', {'a': self.local, 'b': self.local})['ok'])
            self.assertFalse(self.call('POST', '/api/replicas/main', {'path': '/etc'})['ok'])

    def test_only_a_known_local_replica_is_hashed_from_the_dashboard(self):
        with mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.start_hashing') as start_hashing:
            self.assertFalse(self.call('POST', '/api/home/hash', {'path': '/etc'})['ok'])
            self.assertFalse(self.call('POST', '/api/home/hash', {'path': 'cloud/photos'})['ok'])
            self.assertTrue(self.call('POST', '/api/home/hash', {'path': self.local})['ok'])
        start_hashing.assert_called_once_with(self.local, True)

    def test_a_replica_is_hashed_without_its_media_files_and_they_are_added_back_as_it_goes(self):
        with mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.start_hashing') as start_hashing:
            self.call('POST', '/api/home/hash', {'path': self.local, 'media': False})
        start_hashing.assert_called_once_with(self.local, False)
        job = mock.Mock()
        with mock.patch('dirdelta.hashes.hashing.job_for', return_value=job):
            self.call('POST', '/api/home/hash', {'path': self.local, 'only_media': True, 'media': True})
        job.set_media.assert_called_once_with(True)


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
