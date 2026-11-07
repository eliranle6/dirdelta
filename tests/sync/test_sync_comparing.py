"""Comparing the files of the same size at the same paths on request, and finding the files that
differ again as the replicas are hashed"""
import concurrent.futures
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.hashes import hashing
from dirdelta.matching import differing
from dirdelta.matching import elsewhere
from dirdelta.sync import comparing
from dirdelta.sync import dirsync_main
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from sync_menu_support import MainMenuTest


def _done(changes):
    future = concurrent.futures.Future()
    future.set_result(changes)
    return future


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.roots = []
        for name in ('a', 'b'):
            root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-comparing-%s-' % (name,)))
            self.addCleanup(shutil.rmtree, root, ignore_errors=True)
            self.roots.append(root)

    def write(self, files):
        for root, contents in zip(self.roots, files[1:]):
            helpers.make_files(root, [files[0]])
            with open(os.path.join(root, files[0]), 'w') as f:
                f.write(contents)

    def test_the_files_are_read_and_whats_told_is_kept(self):
        self.write(('same.txt', 'abc', 'abc'))
        self.write(('other.txt', 'abc', 'xyz'))
        a, b = [localdiskdirtree.LocalReplica(root) for root in self.roots]
        compared = {}
        with mock.patch('sys.stdout.isatty', return_value=False):
            nr_differ = comparing.compare(['other.txt', 'same.txt', 'gone.txt'], a, b, elsewhere.Index(a),
                                          elsewhere.Index(b), compared)
        self.assertEqual(nr_differ, 1)
        # (One that can't be read isn't noted)
        self.assertEqual(compared, {'other.txt': (3, 3, False), 'same.txt': (3, 3, True)})
        # Then found as they are
        found = differing.find(a, b, compared)
        self.assertEqual(list(found), ['other.txt'])
        self.assertEqual(found.uncompared, [])

    def test_the_option_says_how_many_are_left(self):
        self.assertEqual(comparing.shown_as(_done(differing.Changes({}, ['x', 'y']))),
                         "Compare the files of the same size at the same paths in both, not compared yet (2 files)")
        self.assertIsInstance(comparing.shown_as(_done(differing.Changes({}, []))), picker.Disabled)
        self.assertIsInstance(comparing.shown_as(concurrent.futures.Future()), picker.Disabled)


class _Job(object):
    def __init__(self):
        self.state, self.nr_done = hashing.HASHING, 0

    def progress(self):
        return mock.Mock(state=self.state, nr_done=self.nr_done)


class AsHashedTest(unittest.TestCase):
    def test_found_again_once_more_are_hashed_and_a_job_is_done_or_a_while_went_by(self):
        job = _Job()
        as_hashed = comparing.AsHashed([job])
        as_hashed.found()
        uncompared = _done(differing.Changes({}, ['x']))
        # Nothing hashed since
        self.assertFalse(as_hashed.is_due(uncompared))
        job.nr_done = 5
        self.assertFalse(as_hashed.is_due(uncompared))
        with mock.patch('time.monotonic', return_value=as_hashed._found_at + comparing.REFIND_INTERVAL):
            self.assertTrue(as_hashed.is_due(uncompared))
        job.state = hashing.DONE
        self.assertTrue(as_hashed.is_due(uncompared))
        # None left to compare, or not found yet: never
        self.assertFalse(as_hashed.is_due(_done(differing.Changes({}, []))))
        self.assertFalse(as_hashed.is_due(concurrent.futures.Future()))


class MenuTest(MainMenuTest):
    def test_the_option_compares_them_and_finds_the_files_that_differ_again_with_what_it_told(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.uncompared = ['x']
        answers = [comparing.COMPARE, dirsync_main.BACK]

        def compare(relpaths, src, dst, src_index, dst_index, compared):
            compared['x'] = (3, 3, False)
            return 1
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.sync.comparing.compare', side_effect=compare) as compare_call:
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(compare_call.call_args.args[0], ['x'])
        self.assertEqual(self.compared_given, [{}, {'x': (3, 3, False)}])
        # Only the files that differ were found again, not what each way lacks
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])
