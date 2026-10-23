import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree

COPY = interactive_dir_sync.InteractiveDirSync._OPTION_COPY
REMOVE = interactive_dir_sync.InteractiveDirSync._OPTION_REMOVE
NOTHING = interactive_dir_sync.InteractiveDirSync._OPTION_NOTHING


class InteractiveDirSyncTest(unittest.TestCase):
    """src has a.txt and sub/b.txt, dst has only a.txt, so sub/b.txt is the one missing file."""

    def setUp(self):
        self.src_root = tempfile.mkdtemp(prefix='dirstuff-sync-src-')
        self.dst_root = tempfile.mkdtemp(prefix='dirstuff-sync-dst-')
        helpers.make_files(self.src_root, ['a.txt', 'sub/b.txt'])
        helpers.make_files(self.dst_root, ['a.txt'])
        self.messages = []
        patcher = mock.patch('cursesswitch.print_string', side_effect=lambda s, *a: self.messages.append(s))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.src_root, ignore_errors=True)
        shutil.rmtree(self.dst_root, ignore_errors=True)

    def _sync(self, menu_answers, choose=helpers.all_files):
        src = localdiskdirtree.factory(self.src_root, silent=True)
        dst = localdiskdirtree.factory(self.dst_root, silent=True)
        with helpers.scripted_tree_picker(choose), helpers.scripted_option_picker(menu_answers):
            interactive_dir_sync.InteractiveDirSync(src, dst).sync()
        return src, dst

    def test_copy_copies_missing_file_and_then_reports_nothing_left(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', False):
            self._sync([COPY])

        with open(os.path.join(self.dst_root, 'sub/b.txt')) as f:
            self.assertEqual(f.read(), 'sub/b.txt')
        self.assertIn('Nothing to synchronize', self.messages[-1])

    def test_dry_run_copy_leaves_disk_untouched(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', True):
            self._sync([COPY])

        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

    def test_remove_deletes_file_from_src_and_from_the_diff(self):
        src, dst = self._sync([REMOVE])

        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))
        self.assertIsNone(src.get_node('/sub/b.txt'))
        self.assertIn('Nothing to synchronize', self.messages[-1])

    def test_do_nothing_changes_nothing(self):
        self._sync([NOTHING])

        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

    def test_quitting_the_action_menu_ends_sync(self):
        self._sync([None])  # Would raise IndexError if sync asked the menu again

    def test_selecting_nothing_ends_sync_without_a_menu(self):
        with helpers.scripted_option_picker([]) as picker_class:
            src = localdiskdirtree.factory(self.src_root, silent=True)
            dst = localdiskdirtree.factory(self.dst_root, silent=True)
            with helpers.scripted_tree_picker(lambda tree: []):
                interactive_dir_sync.InteractiveDirSync(src, dst).sync()
        picker_class.assert_not_called()


if __name__ == '__main__':
    unittest.main()
