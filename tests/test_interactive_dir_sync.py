import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import dirtree
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree

COPY = interactive_dir_sync.InteractiveDirSync.COPY
REMOVE = interactive_dir_sync.InteractiveDirSync.REMOVE


class InteractiveDirSyncTest(unittest.TestCase):
    """src has a.txt and sub/b.txt, dst has only a.txt, so sub/b.txt is the one missing file."""

    def setUp(self):
        self.src_root = tempfile.mkdtemp(prefix='dirstuff-sync-src-')
        self.dst_root = tempfile.mkdtemp(prefix='dirstuff-sync-dst-')
        helpers.make_files(self.src_root, ['a.txt', 'sub/b.txt'])
        helpers.make_files(self.dst_root, ['a.txt'])
        self.messages = []
        patcher = mock.patch('dirdelta.messages.print_line', side_effect=lambda s, *a: self.messages.append(s))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.src_root, ignore_errors=True)
        shutil.rmtree(self.dst_root, ignore_errors=True)

    def _sync(self, action, choose=helpers.all_files):
        src = localdiskdirtree.factory(self.src_root, silent=True)
        dst = localdiskdirtree.factory(self.dst_root, silent=True)
        with helpers.scripted_tree_picker(choose):
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(action)
        return src, dst

    def test_copy_copies_missing_file_and_then_reports_nothing_left(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', False):
            self._sync(COPY)

        with open(os.path.join(self.dst_root, 'sub/b.txt')) as f:
            self.assertEqual(f.read(), 'sub/b.txt')
        self.assertIn('Nothing to synchronize', self.messages[-1])

    def test_dry_run_copy_leaves_disk_untouched(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', True):
            self._sync(COPY)

        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))
        # Not even the dir it would have gone into
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub')))

    def test_dry_run_copy_says_so(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', True):
            self._sync(COPY)

        self.assertIn('Dry run, not copying /sub/b.txt (1 out of 1)', self.messages)
        self.assertTrue(any(message.startswith('Dry run: nothing was copied to')
                            for message in self.messages))

    def test_copy_reports_what_it_copied(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', False):
            self._sync(COPY)

        self.assertIn('Copying /sub/b.txt (1 out of 1)', self.messages)
        self.assertIn('Copied 1 files to %s' % (os.path.realpath(self.dst_root),), self.messages)

    def test_remove_deletes_file_from_src_and_from_the_diff(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', False):
            src, dst = self._sync(REMOVE)

        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))
        self.assertIsNone(src.get_node('/sub/b.txt'))
        self.assertIn('Removing /sub/b.txt (1 out of 1)', self.messages)
        self.assertIn('Removed 1 files from %s' % (os.path.realpath(self.src_root),), self.messages)
        self.assertIn('Nothing to synchronize', self.messages[-1])

    def test_dry_run_remove_leaves_disk_untouched(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', True):
            src, dst = self._sync(REMOVE)

        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))
        # The tree is updated as if it was removed, like a dry run copy's
        self.assertIsNone(src.get_node('/sub/b.txt'))
        self.assertIn('Dry run, not removing /sub/b.txt (1 out of 1)', self.messages)
        self.assertTrue(any(message.startswith('Dry run: nothing was removed from')
                            for message in self.messages))

    def test_quitting_the_file_picker_ends_sync(self):
        self._sync(COPY, choose=lambda tree: None)

        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))
        self.assertIn("Sync ended by user's request.", self.messages)

    def test_after_acting_the_rest_is_offered_again(self):
        helpers.make_files(self.src_root, ['sub/c.txt'])
        offered = []

        def choose(tree):
            files = helpers.all_files(tree)
            offered.append([entry.relpath for entry in files])
            # The first file only the first time, then quit
            return files[:1] if len(offered) == 1 else None

        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', False):
            self._sync(COPY, choose)

        self.assertEqual(offered, [['/sub/b.txt', '/sub/c.txt'], ['/sub/c.txt']])
        self.assertTrue(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/c.txt')))

    def test_picking_only_dirs_ends_sync(self):
        # Enter with nothing picked doesn't return; picking only dirs picks no files
        self._sync(COPY, choose=lambda tree: [node.data for node in tree.all_nodes()
                                              if isinstance(node.data, dirtree.DirEntry)])
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

if __name__ == '__main__':
    unittest.main()
