import contextlib
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
YES = interactive_dir_sync.InteractiveDirSync.CONFIRM_YES
NO = interactive_dir_sync.InteractiveDirSync.CONFIRM_NO


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

    def _sync(self, action, choose=helpers.all_files, confirmations=None):
        """Sync, answering each confirmation with the next of confirmations (by default, Yes to all)"""
        src = localdiskdirtree.factory(self.src_root, silent=True)
        dst = localdiskdirtree.factory(self.dst_root, silent=True)
        answers = (helpers.scripted_option_picker(confirmations) if confirmations is not None else
                   mock.patch('dirdelta.picker.pick_option', return_value=YES))
        with helpers.scripted_tree_picker(choose), answers as self.pick_option:
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(action)
        return src, dst

    def test_copy_copies_missing_file(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            src, dst = self._sync(COPY)

        with open(os.path.join(self.dst_root, 'sub/b.txt')) as f:
            self.assertEqual(f.read(), 'sub/b.txt')
        # So the next diff doesn't list it
        self.assertIsNotNone(dst.get_node('sub/b.txt'))

    def test_dry_run_copy_leaves_disk_untouched(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._sync(COPY)

        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))
        # Not even the dir it would have gone into
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub')))

    def test_dry_run_copy_leaves_the_trees_untouched(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            src, dst = self._sync(COPY)

        self.assertIsNone(dst.get_node('sub/b.txt'))
        self.assertIsNone(dst.get_node('sub'))

    def test_dry_run_copy_says_so(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._sync(COPY)

        self.assertIn('Dry run, not copying sub/b.txt (1 out of 1)', self.messages)
        self.assertTrue(any(message.startswith('Dry run complete: nothing was copied to')
                            for message in self.messages))

    def test_copy_reports_what_it_copied(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._sync(COPY)

        self.assertIn('Copying sub/b.txt (1 out of 1)', self.messages)
        self.assertIn('Copy complete: copied 1 of 1 files to %s' % (os.path.realpath(self.dst_root),), self.messages)

    def test_copy_report_ends_saying_its_complete(self):
        # The destination is rescanned after copying, quietly
        src = localdiskdirtree.factory(self.src_root)
        dst = localdiskdirtree.factory(self.dst_root)
        last_lines = []

        @contextlib.contextmanager
        def progress_screen(title, label=None):
            yield
            last_lines.append(self.messages[-1])

        with helpers.scripted_tree_picker(helpers.all_files), \
                mock.patch('dirdelta.picker.pick_option', return_value=YES), \
                mock.patch('dirdelta.messages.progress_screen', progress_screen):
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(COPY)

        self.assertEqual(len(last_lines), 1)
        self.assertTrue(last_lines[0].startswith('Dry run complete: nothing was copied to'), last_lines)

    def test_remove_deletes_file_from_src_and_from_the_diff(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            src, dst = self._sync(REMOVE)

        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))
        self.assertIsNone(src.get_node('sub/b.txt'))
        self.assertIn('Removing sub/b.txt (1 out of 1)', self.messages)
        self.assertIn('Remove complete: removed 1 of 1 files from %s' % (os.path.realpath(self.src_root),), self.messages)

    def test_dry_run_remove_leaves_disk_untouched(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            src, dst = self._sync(REMOVE)

        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))
        # Nor the tree: the next diff still lists it
        self.assertIsNotNone(src.get_node('sub/b.txt'))
        self.assertIn('Dry run, not removing sub/b.txt (1 out of 1)', self.messages)
        self.assertTrue(any(message.startswith('Dry run complete: nothing was removed from')
                            for message in self.messages))

    def test_confirmation_starts_with_no_and_says_what_it_will_do(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._sync(COPY)

        options, = self.pick_option.call_args.args
        self.assertEqual(options[0], NO)
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        self.assertEqual(header[0], 'Copy 1 files from %s to %s?' % (os.path.realpath(self.src_root),
                                                                     os.path.realpath(self.dst_root)))
        self.assertEqual(header[1], '  sub/b.txt')
        self.assertIn('dry run', header[-1])

    def test_no_picks_again_from_the_same_picks_and_changes_nothing(self):
        picked_args = []

        def pick_from_tree(tree, picked=None, **_):
            picked_args.append(picked)
            # The files, then quit
            return helpers.all_files(tree) if len(picked_args) == 1 else None

        src = localdiskdirtree.factory(self.src_root, silent=True)
        dst = localdiskdirtree.factory(self.dst_root, silent=True)
        with mock.patch('dirdelta.picker.pick_from_tree', side_effect=pick_from_tree), \
                helpers.scripted_option_picker([NO]), \
                mock.patch('dirdelta.dryrun.DRYRUN', False):
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(REMOVE)

        self.assertIsNone(picked_args[0])
        self.assertEqual([entry.relpath for entry in picked_args[1]], ['sub/b.txt'])
        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))

    def test_quitting_the_confirmation_is_no(self):
        nr_picks = []

        def choose(tree):
            # The files, then quit
            nr_picks.append(1)
            return helpers.all_files(tree) if len(nr_picks) == 1 else None

        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._sync(REMOVE, choose, confirmations=[None])

        self.assertEqual(len(nr_picks), 2)
        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))

    def test_quitting_the_file_picker_ends_sync(self):
        self._sync(COPY, choose=lambda tree: None)

        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

    def test_after_acting_sync_ends(self):
        # Back to the main menu, rather than offering the files left again
        helpers.make_files(self.src_root, ['sub/c.txt'])
        offered = []

        def choose(tree):
            files = helpers.all_files(tree)
            offered.append([entry.relpath for entry in files])
            return files[:1]

        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._sync(COPY, choose)

        self.assertEqual(offered, [['sub/b.txt', 'sub/c.txt']])
        self.assertTrue(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/c.txt')))

    def test_nothing_missing_says_so_without_a_picker(self):
        helpers.make_files(self.dst_root, ['sub/b.txt'])
        with mock.patch('dirdelta.messages.show') as show:
            self._sync(COPY, choose=lambda tree: self.fail('no picker expected'))
        title, lines, _ = show.call_args.args
        self.assertEqual(title, 'Nothing to copy')
        self.assertEqual(lines, ["%s has all of %s's files." % (os.path.realpath(self.dst_root),
                                                              os.path.realpath(self.src_root))])

    def test_picking_only_dirs_ends_sync(self):
        # Enter with nothing picked doesn't return; picking only dirs picks no files
        self._sync(COPY, choose=lambda tree: [node.data for node in tree.all_nodes()
                                              if isinstance(node.data, dirtree.DirEntry)])
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

if __name__ == '__main__':
    unittest.main()
