"""A replica's Index: built once, kept up to date, while files change"""
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers
from dirdelta.matching import elsewhere
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree
from elsewhere_support import ChangingDuringAListing, SizedTree, SlowReplica, previews_of


class IndexTest(unittest.TestCase):
    def test_built_once_then_kept_up_to_date(self):
        dst = SizedTree('/dst', {'a/x': 1})
        index = elsewhere.Index(dst)
        self.assertFalse(index.is_built())
        index.build()
        dst.add_file_by_relpath('b/x')
        index.build()
        self.assertEqual(index.files_named('x'), {'a/x': 1})
        index.add('c/x', 3)
        index.move('a/x', 'd/x')
        index.remove('c/x')
        self.assertEqual(index.files_named('x'), {'d/x': 1})
        self.assertEqual(index.names_in('d'), {'x'})
        self.assertEqual(index.names_in('a'), set())
        index.invalidate()
        index.build()
        self.assertEqual(sorted(index.files_named('x')), ['a/x', 'b/x'])

    def test_a_hash_is_worked_out_once_and_moves_with_its_file(self):
        dst = SizedTree('/dst', {'a/x': 1}, hashes={'a/x': 'H'})
        index = elsewhere.Index(dst)
        index.build()
        self.assertEqual(index.content_hash('a/x', 'sha256'), 'H')
        self.assertEqual(index.content_hash('a/x', 'sha256'), 'H')
        self.assertEqual(dst.hashed, ['a/x'])
        index.move('a/x', 'b/x')
        self.assertEqual(index.content_hash('b/x', 'sha256'), 'H')
        self.assertEqual(dst.hashed, ['a/x'])
        index.remove('b/x')
        self.assertIsNone(index.content_hash('b/x', 'sha256'))

    def test_changes_before_its_built_are_in_once_it_is(self):
        dst = SizedTree('/dst', {})
        index = elsewhere.Index(dst)
        index.add('x', 1)
        dst.add_file_by_relpath('y')
        index.build()
        self.assertEqual(index.files_named('y'), {'y': None})

    def test_a_local_dir_it_cant_list_is_said(self):
        src = SizedTree('/src', {'x': 1})
        dst = localdiskdirtree.LocalDiskDirTree('/src', True)
        with mock.patch('dirdelta.trees.localscan.subprocess.Popen', side_effect=OSError("no find")):
            sent = previews_of(['x'], src, dst)
        self.assertEqual(sent.defaults[-1][-1], "no find")


class KeptUpToDateTest(unittest.TestCase):
    """An index needn't be told by hand: its replica tells it"""
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirdelta-index-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        helpers.make_files(self.root, ['a/x', 'b/y', 'gone'])
        self.replica = localdiskdirtree.LocalReplica(self.root)
        self.index = elsewhere.Index(self.replica)
        self.index.build()
        patcher = mock.patch('dirdelta.util.dryrun.DRYRUN', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('dirdelta.ui.messages.print_line')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_moved_file_and_dir(self):
        self.replica.move_files([('a/x', 'c/z')])
        self.assertEqual(list(self.index.files_named('z')), ['c/z'])
        self.assertEqual(self.index.files_named('x'), {})
        self.replica.move_files([('b/y', 'd/y')])
        self.assertEqual(list(self.index.files_named('y')), ['d/y'])

    def test_a_removed_file(self):
        self.replica.remove_files([entries.FileEntry('gone', 'gone', os.path.join(self.root, 'gone'))])
        self.assertEqual(self.index.files_named('gone'), {})

    def test_a_copy_within_and_to_another_replica(self):
        self.replica.copy_files_within([('gone', 'copy')])
        self.assertEqual(self.index.files_named('copy'), {'copy': 4})
        other_root = tempfile.mkdtemp(prefix='dirdelta-index-other-')
        self.addCleanup(shutil.rmtree, other_root, ignore_errors=True)
        other = localdiskdirtree.LocalReplica(other_root)
        other_index = elsewhere.Index(other)
        other_index.build()
        self.replica.move_files([('gone', 'there')], other)
        self.assertEqual(self.index.files_named('gone'), {})
        self.assertEqual(other_index.files_named('there'), {'there': 4})

    def test_a_trees_rescan_keeps_who_listens(self):
        tree = localdiskdirtree.LocalDiskDirTree(self.root, True)
        tree.update_from_filesystem()
        index = elsewhere.Index(tree)
        index.build()
        tree.rescan()
        tree.move_files([('a/x', 'c/z')])
        self.assertEqual(list(index.files_named('z')), ['c/z'])


class ChangesDuringABuildTest(unittest.TestCase):
    def built(self, listed, during):
        replica = ChangingDuringAListing(listed, None)
        index = elsewhere.Index(replica)
        replica.during = lambda: during(index, replica)
        index.build()
        return index

    def test_a_file_made_during_it_is_in_it(self):
        index = self.built({'a/x': 1}, lambda index, _: index.add('a/new', 2))
        self.assertEqual(index.files_named('new'), {'a/new': 2})
        self.assertEqual(sorted(index.relpaths()), ['a/new', 'a/x'])

    def test_a_file_removed_during_it_isnt_in_it(self):
        index = self.built({'a/x': 1, 'a/y': 1}, lambda index, _: index.remove('a/x'))
        self.assertEqual(index.relpaths(), ['a/y'])
        self.assertEqual(index.names_in('a'), {'y'})

    def test_a_file_moved_during_it_is_where_it_went_with_its_size(self):
        index = self.built({'a/x': 7}, lambda index, _: index.move('a/x', 'b/z'))
        self.assertEqual(index.files_named('z'), {'b/z': 7})
        self.assertEqual(index.files_named('x'), {})

    def test_one_moved_before_the_listing_saw_it_keeps_its_size(self):
        index = self.built({'b/z': 7}, lambda index, _: index.move('a/x', 'b/z'))
        self.assertEqual(index.files_named('z'), {'b/z': 7})

    def test_invalidated_during_it_its_listed_anew(self):
        replica = ChangingDuringAListing({'old': 1}, None)
        index = elsewhere.Index(replica)

        def during():
            replica.listed = {'new': 2}
            index.invalidate()
        replica.during = during
        index.build()
        self.assertEqual(index.relpaths(), ['new'])

    def test_stopped_it_isnt_built_and_the_changes_are_dropped(self):
        replica = ChangingDuringAListing({'a': 1}, None)
        index = elsewhere.Index(replica)

        def during():
            index.add('b', 1)
            raise KeyboardInterrupt()
        replica.during = during
        with self.assertRaises(KeyboardInterrupt):
            index.build()
        self.assertFalse(index.is_built())
        index.build()
        self.assertEqual(index.relpaths(), ['a'])

    def test_two_threads_build_it_once(self):
        replica = ChangingDuringAListing({'a': 1}, None)
        calls = []
        real = replica.files_by_name
        replica.files_by_name = lambda progress=None: (calls.append(1), time.sleep(0.05), real(progress))[2]
        index = elsewhere.Index(replica)
        threads = [threading.Thread(target=index.build) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(calls), 1)

    def test_reading_while_files_change_on_another_thread(self):
        replica = ChangingDuringAListing({'f%d' % (number,): 1 for number in range(200)}, None)
        index = elsewhere.Index(replica)
        index.build()
        errors = []
        is_done = threading.Event()

        def read():
            try:
                while not is_done.is_set():
                    index.relpaths()
                    index.names_in('')
            except RuntimeError as error:
                errors.append(error)
        reader = threading.Thread(target=read)
        reader.start()
        for number in range(3000):
            index.add('new%d' % (number,), 1)
        is_done.set()
        reader.join()
        self.assertEqual(errors, [])


class ReadsWhileItChangesTest(unittest.TestCase):
    def setUp(self):
        self.replica = SlowReplica()
        self.index = elsewhere.Index(self.replica)

    def test_a_hash_read_while_the_file_moved_isnt_kept_as_its_path(self):
        self.replica.during_read = lambda: self.index.move('a', 'b')
        self.assertEqual(self.index.content_hash('a', 'sha1'), 'read-of-a')
        self.assertEqual(self.index._hashes.get('a'), None)

    def test_a_date_read_while_the_file_was_removed_isnt_kept(self):
        self.replica.during_read = lambda: self.index.remove('a')
        self.assertEqual(self.index.date_taken('a'), 'date-of-a')
        self.assertNotIn('a', self.index._dates_taken)
        self.replica.during_read = lambda: None
        self.index.date_taken('a')
        self.assertIn('a', self.index._dates_taken)

    def test_many_threads_reading_while_files_change(self):
        errors = []
        is_done = threading.Event()

        def read(number):
            try:
                while not is_done.is_set():
                    self.index.content_hash('f%d' % (number % 5,), 'sha1')
                    self.index.known('f%d' % (number % 5,))
                    self.index.date_taken('f%d' % (number % 5,))
                    self.index.hash_algorithms()
                    self.index.files_hashed('sha1', 'x')
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=read, args=(number,)) for number in range(4)]
        for thread in threads:
            thread.start()
        for number in range(3000):
            self.index.move('f%d' % (number % 5,), 'g%d' % (number,))
            self.index.remove('g%d' % (number,))
        is_done.set()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
