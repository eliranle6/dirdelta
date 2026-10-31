import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import dirtree
from dirdelta import hashes_screen
from dirdelta import hashing
from dirdelta import localdiskdirtree
from dirdelta import picker


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
        with mock.patch('dirdelta.picker.pick_option') as pick:
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
        self.assertIn("  6 of 10 files left (1.0 KB of 2.0 KB): /photos", header)
        self.assertIn("recommended", header)
        # Not now: not started
        self.assertEqual(job.started, 0)

    def test_in_the_background_its_started(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen.HASH_IN_BACKGROUND]), \
                mock.patch('dirdelta.hashes_screen.wait') as wait:
            hashes_screen.offer([job])
        self.assertEqual(job.started, 1)
        wait.assert_not_called()

    def test_now_its_started_and_waited_for(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen.HASH_AND_WAIT]), \
                mock.patch('dirdelta.hashes_screen.wait') as wait:
            hashes_screen.offer([job])
        self.assertEqual(job.started, 1)
        wait.assert_called_once_with([job])

    def test_ones_being_hashed_arent_asked_of(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True))
        job._is_started = True
        with mock.patch('dirdelta.picker.pick_option') as pick:
            hashes_screen.offer([job])
        pick.assert_not_called()


class PrepareTest(unittest.TestCase):
    def test_the_local_replicas_jobs_scanned_once(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-hashes-screen-'))
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(hashing._jobs.pop, root, None)
        helpers.make_files(root, ['x'])
        local = localdiskdirtree.LocalDiskDirTree(root, True)
        other = dirtree.DirTree('/cloud-like')
        with mock.patch('dirdelta.messages.print_line'):
            jobs = hashes_screen.prepare([local, other, local])
        self.assertEqual([job.root for job in jobs], [root])
        self.assertEqual(jobs[0].progress().nr_files, 1)
        self.assertEqual(hashes_screen.jobs_of([other, local]), jobs)

    def test_a_scanned_replicas_listing_is_used_rather_than_listing_it_again(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-hashes-screen-'))
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(hashing._jobs.pop, root, None)
        helpers.make_files(root, ['d/x'])
        with mock.patch('dirdelta.messages.print_line'):
            local = localdiskdirtree.factory(root)
        with mock.patch('dirdelta.hashing._list_files') as list_files, \
                mock.patch('dirdelta.messages.print_line') as print_line:
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
        with mock.patch('dirdelta.messages.print_progress', side_effect=lines.append), \
                mock.patch('dirdelta.messages.print_line', side_effect=lambda line, color=None: lines.append(line)), \
                mock.patch('dirdelta.hashes_screen.time.sleep', side_effect=sleep):
            hashes_screen.wait([job])
        self.assertTrue(any("50%  4 of 10 files, 1.0 KB of 2.0 KB, 512 B/s, ~2 s left" in line for line in lines))
        self.assertTrue(lines[-1].startswith("All hashed: "))

    def test_ctrl_c_goes_on(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True))
        lines = []
        with mock.patch('dirdelta.messages.print_progress'), \
                mock.patch('dirdelta.messages.print_line', side_effect=lambda line, color=None: lines.append(line)), \
                mock.patch('dirdelta.hashes_screen.time.sleep', side_effect=KeyboardInterrupt):
            hashes_screen.wait([job])
        self.assertEqual(lines[-1], "Going on: hashing goes on in the background.")
        self.assertEqual(job.paused, 0)


class DashboardTest(unittest.TestCase):
    def test_it_pauses_and_resumes_a_job(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True))
        job._is_started = True
        toggle = hashes_screen._TOGGLE % ('/photos',)
        with helpers.answering_option_picker([toggle, toggle, hashes_screen.BACK]) as pick:
            hashes_screen.dashboard([job])
        self.assertEqual((job.paused, job.started), (1, 1))
        # It's selected again after it's picked
        self.assertEqual(pick.call_args.kwargs['selected'], toggle)

    def test_what_its_options_show(self):
        job = _Job('/photos', _progress(state=hashing.HASHING, is_started=True, current=['a', 'b'], nr_failed=2,
                                        rate=100))
        job._is_started = True
        with helpers.answering_option_picker([hashes_screen.BACK]) as pick:
            hashes_screen.dashboard([job])
        shown = pick.call_args.kwargs['shown_as']()
        self.assertIn("50%  4 of 10 files", shown[hashes_screen._BAR % ('/photos',)].text)
        state = shown[hashes_screen._STATE % ('/photos',)].text
        self.assertIn("Hashing", state)
        self.assertIn("now a (and 1 more)", state)
        self.assertIn("2 files couldn't be hashed", state)
        self.assertEqual(shown[hashes_screen._TOGGLE % ('/photos',)], "  Pause hashing photos")
        self.assertEqual(shown[''], picker.status([("photos: 50% hashed", 'orange')]))

    def test_a_done_one_cant_be_paused(self):
        job = _Job('/photos', _progress(state=hashing.DONE))
        shown = hashes_screen._jobs_shown([job])
        self.assertIsInstance(shown[hashes_screen._TOGGLE % ('/photos',)], picker.Disabled)

    def test_its_files_and_scanning_again(self):
        job = _Job('/photos', _progress())
        with helpers.answering_option_picker([hashes_screen._FILES % ('/photos',), hashes_screen._RESCAN % ('/photos',),
                                              hashes_screen.BACK]), \
                mock.patch('dirdelta.hashes_screen.view_files') as view_files, \
                mock.patch.object(job, 'scan_in_background') as scan:
            hashes_screen.dashboard([job])
        view_files.assert_called_once_with(job)
        scan.assert_called_once_with()

    def test_a_cloud_replicas_hashes(self):
        cloud = mock.Mock()
        cloud.displayname.return_value = 'cloud/d'
        cloud.iter_files.return_value = [mock.Mock(relpath=relpath) for relpath in 'abc']
        cloud.known_hashes.side_effect = lambda relpath: {'a': ('sha1', 'sha256'), 'b': ('sha256',), 'c': ()}[relpath]
        first, note = hashes_screen._drive_lines(cloud)
        self.assertEqual(first, "  Drive's hashes, none read here: SHA-1 of 1 of 3 files, SHA-256 of 2")
        self.assertIn("1 file have no SHA-1 in the cache", note)


class MarksTest(unittest.TestCase):
    def setUp(self):
        self.job = hashing.Job('/photos')
        self.job._files = {'a/x': (1, 0), 'a/y': (1, 0), 'z': (1, 0)}
        self.job._is_scanned = True

    def test_each_file_after_its_mark_then_only_the_changed_ones(self):
        marks = hashes_screen.Marks(self.job, ['a/x', 'z'], [self.job])
        first = marks()
        self.assertEqual({relpath: shown for relpath, shown in first.items() if relpath},
                         {'a/x': 'x  ' + hashing.NOT_HASHED_TAG, 'z': 'z  ' + hashing.NOT_HASHED_TAG})
        self.assertEqual(first[''], picker.status([("photos: 0% hashed (not hashing)", 'red')]))
        # z is hashed: only it changes
        self.job._hashes['z'] = 'H'
        marks._on_hashed('z', {'sha1': 'H'})
        self.assertEqual({relpath: shown for relpath, shown in marks().items() if relpath},
                         {'z': 'z  ' + hashing.HASHED_TAG})
        marks.close()
        self.assertEqual(self.job._subscribers, [])

    def test_the_ones_being_hashed_and_then_not(self):
        marks = hashes_screen.Marks(self.job, ['a/x', 'z'], [self.job])
        marks()
        self.job._current.add('a/x')
        self.assertEqual(marks()['a/x'], 'x  ' + hashing.HASHING_TAG)
        self.job._current.discard('a/x')
        self.assertEqual(marks()['a/x'], 'x  ' + hashing.NOT_HASHED_TAG)

    def test_more_status_after_the_jobs(self):
        marks = hashes_screen.Marks(None, ['a'], [self.job], lambda: [("Claude: describing 1 file", 'yellow')])
        self.assertEqual(marks(), {'': picker.status([("photos: 0% hashed (not hashing)", 'red'),
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
            self.assertEqual(shown_as()['x'], 'x  ' + hashing.HASHED_TAG)
            with self.assertRaises(picker.PickerClosed):
                on_selection(Selection(), lambda found=None, default=None: sent.update(found))
            return True
        with mock.patch('dirdelta.picker.view_files', side_effect=view_files):
            hashes_screen.view_files(job)
        self.assertEqual(sent['x'], ["This one: 2.0 KB", "SHA-1:", "  abc"])
        self.assertEqual(sent['y'], ["This one: 1 B", "Not hashed yet (hashing is paused)"])


if __name__ == '__main__':
    unittest.main()
