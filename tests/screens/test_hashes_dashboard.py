"""The replicas dashboard"""
import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.hashes import hashing
from dirdelta.known import mounts
from dirdelta.known import replicas
from dirdelta.screens import hashes_screen
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from hashes_screen_support import FakeJob, progress_of


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tree = localdiskdirtree.LocalDiskDirTree('/photos', silent=True)
        self.known = replicas.Replicas()

    def dashboard(self, job, answers, trees=None, **kwargs):
        """The dashboard of trees (default: /photos's, whose job is job), answering answers; returns
        the pick_option mock"""
        with mock.patch('dirdelta.hashes.hashing.registry._jobs', {'/photos': job} if job is not None else {}), \
                helpers.answering_option_picker(answers) as pick:
            hashes_screen.dashboard(trees if trees is not None else [self.tree], self.known, **kwargs)
            # What it showed last, while the jobs are still there
            self.shown = pick.call_args.kwargs['shown_as']()
        return pick

    def test_a_replica_can_be_labeled_and_the_dashboard_says_so_after(self):
        job = FakeJob('/photos', progress_of())
        label = (hashes_screen.names.LABEL, '/photos')
        with mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.os.path.isdir', return_value=True), \
                mock.patch('dirdelta.known.replicanames.label_key', return_value='uuid:U'), \
                mock.patch('dirdelta.screens.label_screen.run', side_effect=lambda known, _: known.set_label('uuid:U', 'mine')) as run:
            pick = self.dashboard(job, [label, hashes_screen.BACK])
        run.assert_called_once_with(self.known, ['/photos'])
        self.assertEqual(self.known.labels, {'uuid:U': 'mine'})
        # Shown anew, on it
        self.assertEqual(pick.call_count, 2)
        self.assertEqual(pick.call_args.kwargs['selected'], label)

    def test_a_replica_without_a_job_can_be_hashed_from_it(self):
        path = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-dashboard-'))
        self.addCleanup(shutil.rmtree, path)
        hash_it = (hashes_screen.names.HASH, path)
        with mock.patch.object(hashing.Job, 'start') as start, mock.patch.object(hashing.Job, 'scan_in_background') as scan:
            pick = self.dashboard(None, [hash_it, hashes_screen.BACK], trees=[], other_paths=[path])
            options = [option.id for option in pick.call_args.args[0] if isinstance(option, picker.Option)]
        start.assert_called_once_with()
        scan.assert_called_once_with()
        # Shown anew, as its job's: it can be paused there
        self.assertEqual(pick.call_count, 2)
        self.assertEqual(pick.call_args.kwargs['selected'], (hashes_screen.names.TOGGLE, path))
        self.assertNotIn(hash_it, options)

    def test_quitting_is_asked_only_while_hashing(self):
        job = FakeJob('/photos', progress_of())
        with mock.patch('dirdelta.hashes.hashing.registry._jobs', {'/photos': job}), \
                helpers.answering_option_picker([hashes_screen.KEEP_HASHING, hashes_screen.QUIT_ANYWAY]) as pick:
            self.assertTrue(hashes_screen.is_ok_to_quit())
            pick.assert_not_called()
            job.start()
            self.assertFalse(hashes_screen.is_ok_to_quit())
            self.assertTrue(hashes_screen.is_ok_to_quit())
        self.assertEqual(helpers.labels_of(pick.call_args.args[0])[0], hashes_screen.KEEP_HASHING)

    def test_a_replica_thats_not_there_cant_be_hashed(self):
        path = '/not/there/at/all'
        self.dashboard(None, [hashes_screen.BACK], trees=[], other_paths=[path])
        self.assertIsInstance(self.shown[(hashes_screen.names.HASH, path)], picker.Disabled)

    def test_one_that_isnt_mounted_or_isnt_there_cant_be_labeled(self):
        # What its path is on now isn't its disk
        self.assertIsInstance(hashes_screen.dashboard_actions.label_option('/no/such/dir', self.known), picker.Disabled)
        mount = mounts.Mount('/mnt/x', '/dev/x', 'ext4', '', '', 'U', None)
        with mock.patch('dirdelta.known.mounts.unmounted', return_value=mount), \
                mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.os.path.isdir', return_value=True):
            self.assertIsInstance(hashes_screen.dashboard_actions.label_option('/mnt/x', self.known), picker.Disabled)
        with mock.patch('dirdelta.known.replicanames.identity', return_value='drive:R:/c'):
            self.assertNotIsInstance(hashes_screen.dashboard_actions.label_option('cloud/c', self.known), picker.Disabled)

    def test_it_pauses_and_resumes_a_job(self):
        job = FakeJob('/photos', progress_of(state=hashing.HASHING, is_started=True))
        job._is_started = True
        toggle = (hashes_screen.names.TOGGLE, '/photos')
        pick = self.dashboard(job, [toggle, toggle, hashes_screen.BACK])
        self.assertEqual((job.paused, job.started), (1, 1))
        # It's selected again after it's picked, q goes back, and it's titled
        self.assertEqual(pick.call_args.kwargs['selected'], toggle)
        self.assertIn(('q', 'back'), pick.call_args.kwargs['key_hints'])
        self.assertEqual(pick.call_args.kwargs['title'], hashes_screen.TITLE)

    def test_what_its_options_show(self):
        job = FakeJob('/photos', progress_of(state=hashing.HASHING, is_started=True, current=['a', 'b'], nr_failed=2,
                                        rate=100))
        job._is_started = True
        self.known.note_seen('path:/photos', '/photos', None, datetime.datetime(2026, 10, 30, 9, 5))
        self.dashboard(job, [hashes_screen.BACK])
        shown = self.shown
        self.assertEqual(shown[(hashes_screen.names.INFO, '/photos')].text, "  10 files, 2.0 KB")
        self.assertIn("  ● Synced 30.10.2026 09:05", [picker.unstyled(option.text) for option in shown.values()
                                                   if isinstance(option, (picker.Disabled, picker.Skipped))])
        self.assertIn("Hashes: [", shown[(hashes_screen.names.BAR, '/photos')].text)
        self.assertIn("50%  4 of 10 files", shown[(hashes_screen.names.BAR, '/photos')].text)
        state = shown[(hashes_screen.names.STATE, '/photos')].text
        self.assertIn("Hashing", state)
        self.assertIn("now a (and 1 more)", state)
        self.assertIn("2 files couldn't be hashed", state)
        self.assertEqual(shown[(hashes_screen.names.TOGGLE, '/photos')], "  Pause hashing photos")
        self.assertEqual(shown[''], picker.segments([("photos: 50% hashed (4/10)", 'orange')]))

    def test_a_done_one_cant_be_paused(self):
        job = FakeJob('/photos', progress_of(state=hashing.DONE))
        with mock.patch('dirdelta.hashes.hashing.registry._jobs', {'/photos': job}):
            shown = hashes_screen.dashboard_lines.jobs_shown([('/photos', self.tree)], {'/photos': 'photos'})
        self.assertIsInstance(shown[(hashes_screen.names.TOGGLE, '/photos')], picker.Disabled)

    def test_its_files_and_scanning_again(self):
        job = FakeJob('/photos', progress_of())
        with mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.view_files') as view_files, \
                mock.patch.object(job, 'scan_in_background') as scan:
            self.dashboard(job, [(hashes_screen.names.FILES, '/photos'), (hashes_screen.names.RESCAN, '/photos'),
                                 hashes_screen.BACK])
        view_files.assert_called_once_with(job)
        scan.assert_called_once_with()

    def test_a_known_replica_without_a_job_says_how_many_hashes_are_kept(self):
        with mock.patch('dirdelta.hashes.hashcache.count_under', return_value=7):
            self.dashboard(None, [hashes_screen.BACK], trees=[], other_paths=['/old', 'cloud/c'])
        shown = self.shown
        self.assertIn("Hashes kept of 7 files", shown[(hashes_screen.names.INFO, '/old')].text)
        self.assertIn("In Google Drive", shown[(hashes_screen.names.INFO, 'cloud/c')].text)
        self.assertEqual(shown[(hashes_screen.names.KNOWN, 0, '/old')].text, "  Never synced before")

    def test_the_pairs_known_come_first_with_their_sync_state(self):
        self.known.record('/photos', 'cloud/p')
        self.known.note_compared('/photos', 'cloud/p', 0, 2, datetime.datetime(2026, 11, 1, 9, 5))
        pick = self.dashboard(None, [hashes_screen.BACK])
        options = [picker.option_id(option) for option in pick.call_args.args[0]]
        self.assertEqual(options[0], hashes_screen.PAIRS_HEADING)
        self.assertEqual(picker.unstyled(self.shown[options[1]].text), "\u00ab /photos <-> cloud/p")
        self.assertEqual(picker.unstyled(self.shown[options[2]].text),
                         "  cloud/p is ahead: it has 2 files that /photos lacks, and lacks none of its "
                         "(as of 01.11.2026 09:05)")
        self.assertIn(hashes_screen.REPLICAS_HEADING, options)
        self.assertIn("The pairs' marks:", pick.call_args.kwargs['help_lines'])

    def test_a_cloud_replicas_hashes(self):
        cloud = mock.Mock()
        cloud.displayname.return_value = 'cloud/d'
        cloud.iter_files.return_value = [mock.Mock(relpath=relpath) for relpath in 'abc']
        cloud.file_size.return_value = 10
        cloud.known_hashes.side_effect = lambda relpath: {'a': ('sha1', 'sha256'), 'b': ('sha256',), 'c': ()}[relpath]
        nr_files, size, first, note = hashes_screen.dashboard_lines.drive_lines(cloud)
        self.assertEqual((nr_files, size), (3, 30))
        self.assertEqual(first, "  Drive's hashes, none read here: SHA-1 of 1 of 3 files, SHA-256 of 2")
        self.assertEqual(note, "  1 file has no hash: Google's own files (Docs, Sheets...)")


if __name__ == '__main__':
    unittest.main()
