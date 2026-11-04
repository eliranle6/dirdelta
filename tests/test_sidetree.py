import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import clouddirtree
from dirdelta import entries
from dirdelta import localdiskdirtree
from dirdelta import sidetree


class ItemsTest(unittest.TestCase):
    def test_a_local_dirs_dirs_and_files_in_order(self):
        root = tempfile.mkdtemp(prefix='dirdelta-sidetree-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['b/x', 'a.txt', 'inbox/y'])
        os.makedirs(os.path.join(root, 'empty'))
        self.assertEqual(sidetree.items(root, excluded='inbox'), ['f a.txt', 'd b', 'f b/x', 'd empty'])

    def test_a_drive_trees_from_its_nodes(self):
        tree = clouddirtree.CloudDirTree('cloud/me')
        tree.add_file_by_relpath('photos/a.jpg')
        self.assertEqual(sidetree.items('cloud/me', tree), ['d photos', 'f photos/a.jpg'])


class MetaTest(unittest.TestCase):
    def test_a_replicas_meta_dir_isnt_listed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            helpers.make_files(tmpdir, ['a.txt', 'meta/hashes.sqlite'])
            self.assertEqual(sidetree.items(tmpdir), ['f a.txt'])


class ListingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirdelta-sidetree-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        helpers.make_files(self.root, ['a.txt', 'meta/h', 'in/y', 'b/x'])
        self.tree = localdiskdirtree.LocalReplica(self.root)
        self.listing = sidetree.Listing(self.root, self.tree, 'in')
        patcher = mock.patch('dirdelta.dryrun.DRYRUN', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('dirdelta.messages.print_line')
        patcher.start()
        self.addCleanup(patcher.stop)

    def listed_times(self, times=2):
        with mock.patch('dirdelta.localscan.scan', wraps=sidetree.localscan.scan) as scan:
            for _ in range(times):
                found = self.listing.items()
        return scan.call_count, found

    def test_its_listed_once_until_something_changes(self):
        self.assertEqual(self.listed_times(), (1, ['f a.txt', 'd b', 'f b/x']))

    def test_what_dirdelta_changes_is_listed_anew(self):
        self.listing.items()
        self.tree.move_files([('a.txt', 'b/moved')])
        self.assertEqual(self.listed_times(), (1, ['d b', 'f b/moved', 'f b/x']))
        self.tree.copy_files_within([('b/moved', 'copy')])
        self.assertIn('f copy', self.listing.items())
        self.tree.remove_files([entries.FileEntry('copy', 'copy', os.path.join(self.root, 'copy'))])
        self.assertNotIn('f copy', self.listing.items())

    def test_a_dry_run_changes_nothing_so_its_not_listed_anew(self):
        self.listing.items()
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.tree.move_files([('a.txt', 'b/moved')])
        self.assertEqual(self.listed_times()[0], 0)

    def test_invalidate(self):
        self.listing.items()
        helpers.make_files(self.root, ['outside'])
        self.assertNotIn('f outside', self.listing.items())
        self.listing.invalidate()
        self.assertIn('f outside', self.listing.items())

    def test_closed_its_not_told_anymore(self):
        self.listing.items()
        self.listing.close()
        self.assertEqual(self.tree._listeners, [])

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_it_says_what_couldnt_be_read(self):
        locked = os.path.join(self.root, 'b')
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        self.listing.items()
        self.assertEqual(len(self.listing.errors), 1)


if __name__ == '__main__':
    unittest.main()
