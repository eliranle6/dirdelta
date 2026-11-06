"""Offering to hash a replica's files, and waiting for it"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.hashes import hashing
from dirdelta.screens import hashes_screen
from dirdelta.trees import dirtree
from dirdelta.trees import localdiskdirtree
from hashes_screen_support import FakeJob, progress_of


class OfferTest(unittest.TestCase):
    def test_all_hashed_ones_are_started_without_asking(self):
        job = FakeJob('/a', progress_of(state=hashing.DONE))
        with mock.patch('dirdelta.ui.picker.pick_option') as pick:
            hashes_screen.offer([job])
        pick.assert_not_called()
        self.assertEqual(job.started, 1)

    def test_nothing_is_first_and_goes_back(self):
        job = FakeJob('/photos', progress_of())
        with helpers.answering_option_picker([hashes_screen.NOTHING]) as pick:
            self.assertFalse(hashes_screen.offer([job]))
        self.assertEqual(pick.call_args.args[0][:2], [hashes_screen.NOTHING, hashes_screen.NOT_NOW])
        self.assertEqual(job.started, 0)
        with helpers.answering_option_picker([None]):
            self.assertFalse(hashes_screen.offer([job]))

    def test_its_asked_with_whats_left(self):
        job = FakeJob('/photos', progress_of())
        with helpers.answering_option_picker([hashes_screen.NOT_NOW]) as pick:
            self.assertTrue(hashes_screen.offer([job]))
        header = pick.call_args.kwargs['header']
        self.assertEqual(header, "Hash unhashed files?\n\n6 files unhashed in photos.\n"
                                 "It helps compare files, but may slow down the machine.")
        # Not now: not started
        self.assertEqual(job.started, 0)

    def test_in_the_background_its_started(self):
        job = FakeJob('/photos', progress_of())
        with helpers.answering_option_picker([hashes_screen.HASH_IN_BACKGROUND]), \
                mock.patch('dirdelta.screens.hashes_screen.offering.wait') as wait:
            hashes_screen.offer([job])
        self.assertEqual(job.started, 1)
        wait.assert_not_called()

    def test_now_its_started_and_waited_for(self):
        job = FakeJob('/photos', progress_of())
        with helpers.answering_option_picker([hashes_screen.HASH_AND_WAIT]), \
                mock.patch('dirdelta.screens.hashes_screen.offering.wait') as wait:
            hashes_screen.offer([job])
        self.assertEqual(job.started, 1)
        wait.assert_called_once_with([job])

    def test_ones_being_hashed_arent_asked_of(self):
        job = FakeJob('/photos', progress_of(state=hashing.HASHING, is_started=True))
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
        with mock.patch('dirdelta.hashes.hashing.job_scanning.list_files') as list_files, \
                mock.patch('dirdelta.ui.messages.print_line') as print_line:
            job, = hashes_screen.prepare([local])
        list_files.assert_not_called()
        print_line.assert_not_called()
        stat = os.stat(os.path.join(root, 'd', 'x'))
        self.assertEqual(job._files, {'d/x': (stat.st_size, stat.st_mtime_ns)})


class WaitTest(unittest.TestCase):
    def test_until_its_done(self):
        job = FakeJob('/photos', progress_of(state=hashing.HASHING, is_started=True, rate=512, current=['a']))
        lines = []

        def sleep(seconds):
            job.progress_of = progress_of(state=hashing.DONE, nr_done=10, size_done=2048)
        with mock.patch('dirdelta.ui.messages.print_progress', side_effect=lines.append), \
                mock.patch('dirdelta.ui.messages.print_line', side_effect=lambda line, color=None: lines.append(line)), \
                mock.patch('dirdelta.screens.hashes_screen.waiting.time.sleep', side_effect=sleep):
            hashes_screen.wait([job])
        self.assertTrue(any("50%  4 of 10 files, 1.0 KB of 2.0 KB, 512 B/s, ~2 s left" in line for line in lines))
        self.assertTrue(lines[-1].startswith("All hashed: "))

    def test_ctrl_c_goes_on(self):
        job = FakeJob('/photos', progress_of(state=hashing.HASHING, is_started=True))
        lines = []
        with mock.patch('dirdelta.ui.messages.print_progress'), \
                mock.patch('dirdelta.ui.messages.print_line', side_effect=lambda line, color=None: lines.append(line)), \
                mock.patch('dirdelta.screens.hashes_screen.waiting.time.sleep', side_effect=KeyboardInterrupt):
            hashes_screen.wait([job])
        self.assertEqual(lines[-1], "Going on: hashing goes on in the background.")
        self.assertEqual(job.paused, 0)


if __name__ == '__main__':
    unittest.main()
