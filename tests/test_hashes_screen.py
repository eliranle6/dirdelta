import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.trees import dirtree
from dirdelta.screens import hashes_screen
from dirdelta.hashes import hashing
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from dirdelta.known import replicas
from dirdelta.known import mounts


class _Job(hashing.Job):
    """A job whose progress is as given, and that's started and paused by hand"""
    def __init__(self, root, progress):
        super(_Job, self).__init__(root)
        self._progress = progress
        self.started = self.paused = 0

    def progress(self):
        return self._progress

    def start(self):
        self.started += 1
        self._is_started = True

    def pause(self):
        self.paused += 1
        self._is_started = False


def _progress(**fields):
    defaults = dict(state=hashing.SCANNED, nr_files=10, nr_done=4, size=2048, size_done=1024, current=[],
                    rate=None, nr_failed=0, is_paused=False, is_started=False)
    defaults.update(fields)
    return hashing.Progress(**defaults)


class OfferTest(unittest.TestCase):
    def test_all_hashed_ones_are_started_without_asking(self):
        job = _Job('/a', _progress(state=hashing.DONE))
        with mock.patch('dirdelta.ui.picker.pick_option') as pick:
            hashes_screen.offer([job])
        pick.assert_not_called()
        self.assertEqual(job.started, 1)

    def test_nothing_is_first_and_goes_back(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen.NOTHING]) as pick:
            self.assertFalse(hashes_screen.offer([job]))
        self.assertEqual(pick.call_args.args[0][:2], [hashes_screen.NOTHING, hashes_screen.NOT_NOW])
        self.assertEqual(job.started, 0)
        with helpers.answering_option_picker([None]):
            self.assertFalse(hashes_screen.offer([job]))

    def test_its_asked_with_whats_left(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen.NOT_NOW]) as pick:
            self.assertTrue(hashes_screen.offer([job]))
        header = pick.call_args.kwargs['header']
        self.assertEqual(header, "Hash unhashed files?\n\n6 files unhashed in photos.\n"
                                 "It helps compare files, but may slow down the machine.")
        # Not now: not started
        self.assertEqual(job.started, 0)

    def test_in_the_background_its_started(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen.HASH_IN_BACKGROUND]), \
                mock.patch('dirdelta.screens.hashes_screen.offering.wait') as wait:
            hashes_screen.offer([job])
        self.assertEqual(job.started, 1)
        wait.assert_not_called()

    def test_now_its_started_and_waited_for(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen.HASH_AND_WAIT]), \
                mock.patch('dirdelta.screens.hashes_screen.offering.wait') as wait:
            hashes_screen.offer([job])
        self.assertEqual(job.started, 1)
        wait.assert_called_once_with([job])

    def test_ones_being_hashed_arent_asked_of(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True))
        job._is_started = True
        with mock.patch('dirdelta.ui.picker.pick_option') as pick:
            hashes_screen.offer([job])
        pick.assert_not_called()


class PrepareTest(unittest.TestCase):
    def test_the_local_replicas_jobs_scanned_once(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-hashes-screen-'))
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(hashing.registry._jobs.pop, root, None)
        helpers.make_files(root, ['x'])
        local = localdiskdirtree.LocalDiskDirTree(root, True)
        other = dirtree.DirTree('/cloud-like')
        with mock.patch('dirdelta.ui.messages.print_line'):
            jobs = hashes_screen.prepare([local, other, local])
        self.assertEqual([job.root for job in jobs], [root])
        self.assertEqual(jobs[0].progress().nr_files, 1)
        self.assertEqual(hashes_screen.jobs_of([other, local]), jobs)

    def test_a_scanned_replicas_listing_is_used_rather_than_listing_it_again(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-hashes-screen-'))
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(hashing.registry._jobs.pop, root, None)
        helpers.make_files(root, ['d/x'])
        with mock.patch('dirdelta.ui.messages.print_line'):
            local = localdiskdirtree.factory(root)
        with mock.patch('dirdelta.hashes.hashing.job_scanning._list_files') as list_files, \
                mock.patch('dirdelta.ui.messages.print_line') as print_line:
            job, = hashes_screen.prepare([local])
        list_files.assert_not_called()
        print_line.assert_not_called()
        stat = os.stat(os.path.join(root, 'd', 'x'))
        self.assertEqual(job._files, {'d/x': (stat.st_size, stat.st_mtime_ns)})


class WaitTest(unittest.TestCase):
    def test_until_its_done(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True, rate=512, current=['a']))
        lines = []

        def sleep(seconds):
            job._progress = _progress(state=hashing.DONE, nr_done=10, size_done=2048)
        with mock.patch('dirdelta.ui.messages.print_progress', side_effect=lines.append), \
                mock.patch('dirdelta.ui.messages.print_line', side_effect=lambda line, color=None: lines.append(line)), \
                mock.patch('dirdelta.screens.hashes_screen.waiting.time.sleep', side_effect=sleep):
            hashes_screen.wait([job])
        self.assertTrue(any("50%  4 of 10 files, 1.0 KB of 2.0 KB, 512 B/s, ~2 s left" in line for line in lines))
        self.assertTrue(lines[-1].startswith("All hashed: "))

    def test_ctrl_c_goes_on(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True))
        lines = []
        with mock.patch('dirdelta.ui.messages.print_progress'), \
                mock.patch('dirdelta.ui.messages.print_line', side_effect=lambda line, color=None: lines.append(line)), \
                mock.patch('dirdelta.screens.hashes_screen.waiting.time.sleep', side_effect=KeyboardInterrupt):
            hashes_screen.wait([job])
        self.assertEqual(lines[-1], "Going on: hashing goes on in the background.")
        self.assertEqual(job.paused, 0)


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
        job = _Job('/photos', _progress())
        label = (hashes_screen.names._LABEL, '/photos')
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
        hash_it = (hashes_screen.names._HASH, path)
        with mock.patch.object(hashing.Job, 'start') as start, mock.patch.object(hashing.Job, 'scan_in_background') as scan:
            pick = self.dashboard(None, [hash_it, hashes_screen.BACK], trees=[], other_paths=[path])
            options = [option.id for option in pick.call_args.args[0] if isinstance(option, picker.Option)]
        start.assert_called_once_with()
        scan.assert_called_once_with()
        # Shown anew, as its job's: it can be paused there
        self.assertEqual(pick.call_count, 2)
        self.assertEqual(pick.call_args.kwargs['selected'], (hashes_screen.names._TOGGLE, path))
        self.assertNotIn(hash_it, options)

    def test_quitting_is_asked_only_while_hashing(self):
        job = _Job('/photos', _progress())
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
        self.assertIsInstance(self.shown[(hashes_screen.names._HASH, path)], picker.Disabled)

    def test_one_that_isnt_mounted_or_isnt_there_cant_be_labeled(self):
        # What its path is on now isn't its disk
        self.assertIsInstance(hashes_screen.dashboard_actions._label_option('/no/such/dir', self.known), picker.Disabled)
        mount = mounts.Mount('/mnt/x', '/dev/x', 'ext4', '', '', 'U', None)
        with mock.patch('dirdelta.known.mounts.unmounted', return_value=mount), \
                mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.os.path.isdir', return_value=True):
            self.assertIsInstance(hashes_screen.dashboard_actions._label_option('/mnt/x', self.known), picker.Disabled)
        with mock.patch('dirdelta.known.replicanames.identity', return_value='drive:R:/c'):
            self.assertNotIsInstance(hashes_screen.dashboard_actions._label_option('cloud/c', self.known), picker.Disabled)

    def test_it_pauses_and_resumes_a_job(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True))
        job._is_started = True
        toggle = (hashes_screen.names._TOGGLE, '/photos')
        pick = self.dashboard(job, [toggle, toggle, hashes_screen.BACK])
        self.assertEqual((job.paused, job.started), (1, 1))
        # It's selected again after it's picked, q goes back, and it's titled
        self.assertEqual(pick.call_args.kwargs['selected'], toggle)
        self.assertIn(('q', 'back'), pick.call_args.kwargs['key_hints'])
        self.assertEqual(pick.call_args.kwargs['title'], hashes_screen.TITLE)

    def test_what_its_options_show(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True, current=['a', 'b'], nr_failed=2,
                                        rate=100))
        job._is_started = True
        self.known.note_seen('path:/photos', '/photos', None, datetime.datetime(2026, 10, 30, 9, 5))
        self.dashboard(job, [hashes_screen.BACK])
        shown = self.shown
        self.assertEqual(shown[(hashes_screen.names._INFO, '/photos')].text, "  10 files, 2.0 KB")
        self.assertIn("  ● Synced 30.10.2026 09:05", [picker.unstyled(option.text) for option in shown.values()
                                                   if isinstance(option, (picker.Disabled, picker.Skipped))])
        self.assertIn("Hashes: [", shown[(hashes_screen.names._BAR, '/photos')].text)
        self.assertIn("50%  4 of 10 files", shown[(hashes_screen.names._BAR, '/photos')].text)
        state = shown[(hashes_screen.names._STATE, '/photos')].text
        self.assertIn("Hashing", state)
        self.assertIn("now a (and 1 more)", state)
        self.assertIn("2 files couldn't be hashed", state)
        self.assertEqual(shown[(hashes_screen.names._TOGGLE, '/photos')], "  Pause hashing photos")
        self.assertEqual(shown[''], picker.segments([("photos: 50% hashed (4/10)", 'orange')]))

    def test_a_done_one_cant_be_paused(self):
        job = _Job('/photos', _progress(state=hashing.DONE))
        with mock.patch('dirdelta.hashes.hashing.registry._jobs', {'/photos': job}):
            shown = hashes_screen.dashboard_lines._jobs_shown([('/photos', self.tree)], {'/photos': 'photos'})
        self.assertIsInstance(shown[(hashes_screen.names._TOGGLE, '/photos')], picker.Disabled)

    def test_its_files_and_scanning_again(self):
        job = _Job('/photos', _progress())
        with mock.patch('dirdelta.screens.hashes_screen.dashboard_actions.view_files') as view_files, \
                mock.patch.object(job, 'scan_in_background') as scan:
            self.dashboard(job, [(hashes_screen.names._FILES, '/photos'), (hashes_screen.names._RESCAN, '/photos'),
                                 hashes_screen.BACK])
        view_files.assert_called_once_with(job)
        scan.assert_called_once_with()

    def test_a_known_replica_without_a_job_says_how_many_hashes_are_kept(self):
        with mock.patch('dirdelta.hashes.hashcache.count_under', return_value=7):
            self.dashboard(None, [hashes_screen.BACK], trees=[], other_paths=['/old', 'cloud/c'])
        shown = self.shown
        self.assertIn("Hashes kept of 7 files", shown[(hashes_screen.names._INFO, '/old')].text)
        self.assertIn("In Google Drive", shown[(hashes_screen.names._INFO, 'cloud/c')].text)
        self.assertEqual(shown[(hashes_screen.names._KNOWN, 0, '/old')].text, "  Never synced before")

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
        nr_files, size, first, note = hashes_screen.dashboard_lines._drive_lines(cloud)
        self.assertEqual((nr_files, size), (3, 30))
        self.assertEqual(first, "  Drive's hashes, none read here: SHA-1 of 1 of 3 files, SHA-256 of 2")
        self.assertEqual(note, "  1 file has no hash: Google's own files (Docs, Sheets...)")


class MarksTest(unittest.TestCase):
    def setUp(self):
        self.job = hashing.Job('/photos')
        self.job._files = {'a/x': (1, 0), 'a/y': (1, 0), 'z': (1, 0)}
        self.job._is_scanned = True

    def test_each_file_after_its_mark_then_only_the_changed_ones(self):
        marks = hashes_screen.Marks(self.job, ['a/x', 'z'], [self.job])
        first = marks()
        self.assertEqual({relpath: picker.unstyled(shown) for relpath, shown in first.items() if relpath},
                         {'a/x': 'x  ' + hashing.NOT_HASHED_TAG, 'z': 'z  ' + hashing.NOT_HASHED_TAG})
        # Its tag in its style
        self.assertEqual(first['z'], picker.styled([('z', None), ('  ', None), (hashing.NOT_HASHED_TAG, 'grey')]))
        self.assertEqual(first[''], picker.segments([("photos: 0% hashed (0/3, not hashing)", 'red')]))
        # z is hashed: only it changes
        self.job._hashes['z'] = 'H'
        marks._on_hashed('z', {'sha1': 'H'})
        self.assertEqual({relpath: picker.unstyled(shown) for relpath, shown in marks().items() if relpath},
                         {'z': 'z  ' + hashing.HASHED_TAG})
        marks.close()
        self.assertEqual(self.job._subscribers, [])

    def test_the_ones_being_hashed_and_then_not(self):
        marks = hashes_screen.Marks(self.job, ['a/x', 'z'], [self.job])
        marks()
        self.job._current.add('a/x')
        self.assertEqual(picker.unstyled(marks()['a/x']), 'x  ' + hashing.HASHING_TAG)
        self.job._current.discard('a/x')
        self.assertEqual(picker.unstyled(marks()['a/x']), 'x  ' + hashing.NOT_HASHED_TAG)

    def test_more_status_after_the_jobs(self):
        marks = hashes_screen.Marks(None, ['a'], [self.job], lambda: [("Claude: describing 1 file", 'yellow')])
        self.assertEqual(marks(), {'': picker.segments([("photos: 0% hashed (0/3, not hashing)", 'red'),
                                                      ("Claude: describing 1 file", 'yellow')])})


class ViewFilesTest(unittest.TestCase):
    def test_its_files_with_their_marks_and_hashes(self):
        job = hashing.Job('/photos')
        job._files = {'x': (2048, 0), 'y': (1, 0)}
        job._is_scanned = True
        job._hashes['x'] = 'abc'
        sent = {}

        class Selection(object):
            moves = ['x', 'y']

            def wait_next(self, timeout=None):
                if not self.moves:
                    raise picker.PickerClosed()
                return self.moves.pop(0)

        def view_files(rootpath, relpaths, header='', shown_as=None, on_selection=None, **_):
            self.assertEqual((rootpath, relpaths), ('/photos', ['x', 'y']))
            self.assertEqual(picker.unstyled(shown_as()['x']), 'x  ' + hashing.HASHED_TAG)
            with self.assertRaises(picker.PickerClosed):
                on_selection(Selection(), lambda found=None, default=None: sent.update(found))
            return True
        with mock.patch('dirdelta.ui.picker.view_files', side_effect=view_files):
            hashes_screen.view_files(job)
        self.assertEqual(sent['x'], ["This one: 2.0 KB", "SHA-1:", "  abc"])
        self.assertEqual(sent['y'], ["This one: 1 B", "Not hashed yet (hashing is paused)"])


if __name__ == '__main__':
    unittest.main()
