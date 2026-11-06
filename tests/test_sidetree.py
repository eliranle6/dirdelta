import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import sidetree


class ItemsTest(unittest.TestCase):
    def test_a_local_dirs_dirs_and_files_in_order(self):
        root = tempfile.mkdtemp(prefix='dirdelta-sidetree-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['b/x', 'a.txt', 'inbox/y'])
        os.makedirs(os.path.join(root, 'empty'))
        self.assertEqual(sidetree._listed(root, None, 'inbox')[0], ['f a.txt', 'd b', 'f b/x', 'd empty'])

    def test_a_drive_trees_from_its_nodes(self):
        tree = clouddirtree.CloudDirTree('cloud/me')
        tree.add_file_by_relpath('photos/a.jpg')
        self.assertEqual(sidetree._listed('cloud/me', tree, None)[0], ['d photos', 'f photos/a.jpg'])



class ListingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirdelta-sidetree-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        helpers.make_files(self.root, ['a.txt', 'meta/h', 'in/y', 'b/x'])
        self.tree = localdiskdirtree.LocalReplica(self.root)
        self.listing = sidetree.Listing(self.root, self.tree, 'in')
        patcher = mock.patch('dirdelta.util.dryrun.DRYRUN', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('dirdelta.ui.messages.print_line')
        patcher.start()
        self.addCleanup(patcher.stop)

    def listed_times(self, times=2):
        with mock.patch('dirdelta.trees.localscan.scan', wraps=sidetree.localscan.scan) as scan:
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

    def test_it_goes_as_deep_as_its_replica(self):
        helpers.make_files(self.root, ['deep/er/still/f.txt'])
        tree = localdiskdirtree.LocalReplica(self.root, True, 2)
        listing = sidetree.Listing(self.root, tree)
        self.addCleanup(listing.close)
        self.assertIn('d deep/er', listing.items())
        self.assertNotIn('f deep/er/still/f.txt', listing.items())

    def test_whats_asked_is_told_of_the_next_listings_files_once(self):
        told = []
        listing = sidetree.Listing(self.root, self.tree)
        self.addCleanup(listing.close)
        listing.items()
        listing.invalidate(told.append)
        self.assertEqual(told, [])
        listing.items()
        self.assertEqual(len(told), 1)
        self.assertIn('a.txt', told[0])
        listing.invalidate()
        listing.items()
        self.assertEqual(len(told), 1)

    def test_closed_before_its_listed_its_told_so(self):
        told = []
        listing = sidetree.Listing(self.root, self.tree)
        listing.invalidate(told.append)
        listing.close()
        self.assertEqual(told, [None])

    def test_invalidate(self):
        self.listing.items()
        helpers.make_files(self.root, ['outside'])
        self.assertNotIn('f outside', self.listing.items())
        self.listing.invalidate()
        self.assertIn('f outside', self.listing.items())

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_it_says_what_couldnt_be_read(self):
        locked = os.path.join(self.root, 'b')
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        self.listing.items()
        self.assertEqual(len(self.listing.errors), 1)


if __name__ == '__main__':
    unittest.main()
