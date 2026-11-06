"""A local replica: its scan, its files' info and hashes, and rescanning it"""
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.hashes import hashcache
from dirdelta.trees import dirtree
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree
from localdiskdirtree_support import LocalDiskDirTreeTest


class KeptHashesTest(unittest.TestCase):
    """A file's hash in the hash cache is kept when dirdelta moves it, or copies it locally"""
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-localdiskdirtree-'))
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['d/x', 'y'])
        self.tree = localdiskdirtree.LocalDiskDirTree(self.root, True)
        for relpath in ('d/x', 'y'):
            self.tree.content_hash(relpath, 'sha1')
        patcher = mock.patch('dirdelta.ui.messages.print_line')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_moves_and_copies_to_another_replica(self):
        other_root = tempfile.mkdtemp(prefix='dirdelta-other-', dir=os.path.dirname(self.root))
        self.addCleanup(shutil.rmtree, other_root, ignore_errors=True)
        other = localdiskdirtree.LocalReplica(other_root)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.assertEqual(self.tree.move_files([('y', 'e/y2')], other), [('y', 'e/y2')])
            self.assertEqual(self.tree.move_files([('d/x', 'd/x')], other), [('d/x', 'd/x')])
            self.assertEqual(other.copy_files_within([('e/y2', 'copy')], self.tree), [('e/y2', 'copy')])
        self.assertTrue(other.has_file('e/y2'))
        self.assertFalse(self.tree.has_file('y'))
        self.assertNotIn('y', self.tree)
        self.assertTrue(other.has_file('d/x'))
        self.assertFalse(os.path.exists(os.path.join(self.root, 'd')))
        self.assertTrue(self.tree.has_file('copy'))
        self.assertIn('copy', self.tree)
        # Its hash goes with it
        self.assertEqual(hashcache.get(os.path.join(other_root, 'e', 'y2'), 'sha1'),
                         hashlib.sha1(b'y').hexdigest())

    @unittest.skipIf(os.geteuid() == 0, "root can write anywhere")
    def test_a_read_only_ones_files_arent_moved_out_but_can_be_copied(self):
        other_root = tempfile.mkdtemp(prefix='dirdelta-other-', dir=os.path.dirname(self.root))
        self.addCleanup(shutil.rmtree, other_root, ignore_errors=True)
        other = localdiskdirtree.LocalReplica(other_root)
        os.chmod(self.root, 0o555)
        self.addCleanup(os.chmod, self.root, 0o755)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.assertEqual(self.tree.move_files([('y', 'y')], other), [])
            self.assertEqual(self.tree.copy_files_within([('y', 'copy')], other), [('y', 'copy')])
        # Nothing left behind by the move: only the copy
        self.assertEqual(os.listdir(other_root), ['copy'])
        self.assertTrue(self.tree.has_file('y'))

    def test_listed_says_sizes_and_the_hashes_of_what_hasnt_changed(self):
        replica = localdiskdirtree.LocalReplica(self.root)
        path = os.path.join(self.root, 'y')
        # setUp hashed them
        self.assertEqual(replica.listed('sha1')['y'], (1, hashlib.sha1(b'y').hexdigest()))
        self.assertEqual(replica.listed('sha1')['d/x'], (3, hashlib.sha1(b'd/x').hexdigest()))
        # Changed since: its size says so, and the hash is no more
        with open(path, 'w') as f:
            f.write('changed')
        self.assertEqual(replica.listed('sha1')['y'], (7, None))
        self.assertEqual(replica.listed('sha256')['d/x'], (3, None))
        # As each file's asked for one by one
        self.assertEqual(replica.listed('sha1')['d/x'][1], replica.known_hash('d/x', 'sha1'))


class ScanTest(LocalDiskDirTreeTest):
    """Scanning, and what's known of the files"""

    @unittest.skipIf(os.geteuid() == 0, 'root can read anything')
    def test_scan_errors_are_kept_once(self):
        # find_files and find_dirs both hit the locked dir
        locked = os.path.join(self.src_root, 'locked')
        os.makedirs(locked)
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)

        tree = localdiskdirtree.factory(self.src_root, silent=True)

        self.assertEqual(len(tree.scan_errors), 1)
        self.assertIn('Permission denied', tree.scan_errors[0])

    def test_scan_has_files_and_dirs_hidden_ones_too(self):
        tree = self._scan(['visible.txt', 'sub/nested.txt', '.hidden/inner.txt', '.hidden_at_root.txt'])
        self.assertEqual(sorted(entry.relpath for entry in tree.iter_files()),
                         ['.hidden/inner.txt', '.hidden_at_root.txt', 'sub/nested.txt', 'visible.txt'])
        self.assertIsInstance(tree.get_node('sub').data, entries.DirEntry)
        self.assertIsInstance(tree.get_node('.hidden').data, entries.DirEntry)

    def test_scan_keeps_empty_dirs(self):
        os.makedirs(os.path.join(self.src_root, 'empty'))
        tree = self._scan([])
        self.assertIsInstance(tree.get_node('empty').data, entries.DirEntry)

    def test_files_by_name_finds_them_all_with_sizes_unscanned(self):
        self._scan(['a/x.txt', 'b/x.txt', 'y.txt'])
        with open(os.path.join(self.src_root, 'y.txt'), 'w') as f:
            f.write('12345')
        tree = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        found = tree.files_by_name()
        self.assertEqual(sorted(found['x.txt']), [('a/x.txt', 0), ('b/x.txt', 0)])
        self.assertEqual(found['y.txt'], [('y.txt', 5)])
        self.assertNotIn('a', found)
        self.assertEqual(tree.file_size('y.txt'), 5)
        self.assertIsNone(tree.file_size('nope.txt'))

    def test_content_hash_reads_the_file_and_can_be_stopped(self):
        tree = self._scan(['x.txt'])
        with open(os.path.join(self.src_root, 'x.txt'), 'wb') as f:
            f.write(b'abc')
        self.assertEqual(tree.content_hash('x.txt', 'sha1'), hashlib.sha1(b'abc').hexdigest())
        self.assertIsNone(tree.content_hash('nope.txt', 'sha1'))
        with self.assertRaises(dirtree.HashStopped):
            tree.content_hash('x.txt', 'sha256', should_stop=lambda: True)
        self.assertEqual(tree.local_path('x.txt'), os.path.join(os.path.realpath(self.src_root), 'x.txt'))


class RescanTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='dirdelta-rescan-')
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        helpers.make_files(self.tmpdir, ['a.txt', 'd/b.txt'])

    def files(self, tree):
        return sorted(entry.relpath for entry in tree.iter_files())

    def test_a_scanned_tree_sees_whats_on_disk_now(self):
        tree = localdiskdirtree.factory(self.tmpdir, silent=True)
        os.remove(os.path.join(self.tmpdir, 'a.txt'))
        helpers.make_files(self.tmpdir, ['new/c.txt'])
        tree.rescan()
        self.assertEqual(self.files(tree), ['d/b.txt', 'new/c.txt'])
        self.assertEqual(sorted(tree.file_stamps), ['d/b.txt', 'new/c.txt'])

    def test_a_replica_without_a_tree_stays_so(self):
        tree = localdiskdirtree.LocalReplica(self.tmpdir)
        tree.rescan()
        self.assertIsNone(tree.file_stamps)
        self.assertEqual(self.files(tree), [])

    def test_stopped_or_gone_its_as_it_was(self):
        tree = localdiskdirtree.factory(self.tmpdir, silent=True)
        with mock.patch.object(localdiskdirtree.LocalDiskDirTree, 'update_from_filesystem', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                tree.rescan()
        self.assertEqual(self.files(tree), ['a.txt', 'd/b.txt'])
        shutil.rmtree(self.tmpdir)
        with self.assertRaises(OSError):
            tree.rescan()
        self.assertEqual(self.files(tree), ['a.txt', 'd/b.txt'])


if __name__ == '__main__':
    unittest.main()
