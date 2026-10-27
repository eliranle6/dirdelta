import contextlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import clouddirtree
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

    def _sync(self, action, choose=list, confirmations=None):
        """Sync, answering each confirmation with the next of confirmations (by default, Yes to all)"""
        src = localdiskdirtree.factory(self.src_root, silent=True)
        dst = localdiskdirtree.factory(self.dst_root, silent=True)
        answers = (helpers.scripted_option_picker(confirmations) if confirmations is not None else
                   mock.patch('dirdelta.picker.pick_option', return_value=YES))
        with helpers.scripted_files_picker(choose), answers as self.pick_option:
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

        with helpers.scripted_files_picker(list), \
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

        def pick_files(rootpath, relpaths, picked=None, **_):
            picked_args.append(picked)
            # The files, then quit
            return list(relpaths) if len(picked_args) == 1 else None

        src = localdiskdirtree.factory(self.src_root, silent=True)
        dst = localdiskdirtree.factory(self.dst_root, silent=True)
        with mock.patch('dirdelta.picker.pick_files', side_effect=pick_files), \
                helpers.scripted_option_picker([NO]), \
                mock.patch('dirdelta.dryrun.DRYRUN', False):
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(REMOVE)

        self.assertIsNone(picked_args[0])
        self.assertEqual(picked_args[1], ['sub/b.txt'])
        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))

    def test_quitting_the_confirmation_is_no(self):
        nr_picks = []

        def choose(relpaths):
            # The files, then quit
            nr_picks.append(1)
            return list(relpaths) if len(nr_picks) == 1 else None

        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._sync(REMOVE, choose, confirmations=[None])

        self.assertEqual(len(nr_picks), 2)
        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'sub/b.txt')))

    def test_quitting_the_file_picker_ends_sync(self):
        self._sync(COPY, choose=lambda relpaths: None)

        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

    def test_after_acting_sync_ends(self):
        # Back to the main menu, rather than offering the files left again
        helpers.make_files(self.src_root, ['sub/c.txt'])
        offered = []

        def choose(relpaths):
            offered.append(list(relpaths))
            return relpaths[:1]

        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._sync(COPY, choose)

        self.assertEqual(offered, [['sub/b.txt', 'sub/c.txt']])
        self.assertTrue(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/c.txt')))

    def test_nothing_missing_says_so_without_a_picker(self):
        helpers.make_files(self.dst_root, ['sub/b.txt'])
        with mock.patch('dirdelta.messages.show') as show:
            self._sync(COPY, choose=lambda relpaths: self.fail('no picker expected'))
        title, lines, _ = show.call_args.args
        self.assertEqual(title, 'Nothing to copy')
        self.assertEqual(lines, ["%s has all of %s's files." % (os.path.realpath(self.dst_root),
                                                              os.path.realpath(self.src_root))])

    def test_picking_nothing_ends_sync(self):
        self._sync(COPY, choose=lambda relpaths: [])
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'sub/b.txt')))

    def test_picked_files_are_copied_from_src(self):
        # Their entries are made from the picked relpaths only
        copied = []
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.LocalDiskDirTree.copy_inner_entries_from_dirtree',
                           side_effect=lambda tree, source: copied.extend(tree.iter_files())):
            self._sync(COPY)
        self.assertEqual([(entry.relpath, entry.full_filesystem_path()) for entry in copied],
                         [('sub/b.txt', os.path.join(os.path.realpath(self.src_root), 'sub/b.txt'))])

    def test_trees_other_than_two_local_dirs_are_diffed_as_they_are(self):
        # (A cloud tree, say.) Sorted by path components, so each dir's files stay together.
        src = dirtree.DirTree('/src')
        for relpath in ['b/2.txt', 'a b/1.txt', 'a/1.txt', 'c.txt']:
            src.add_file_by_relpath(relpath)
        dst = dirtree.DirTree('/dst')
        dst.add_file_by_relpath('c.txt')
        offered = []
        with helpers.scripted_files_picker(lambda relpaths: offered.append(relpaths)):
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(COPY)
        self.assertEqual(offered, [['a/1.txt', 'a b/1.txt', 'b/2.txt']])

    def test_a_cloud_replica_is_named_as_a_cloud_path(self):
        # Not by its path in Drive (/mein), which reads like a local dir
        src = clouddirtree.CloudDirTree('cloud/mein')
        src.add_file_by_relpath('song.mp3')
        dst = dirtree.DirTree('/local')
        # No, then quitting the picker it goes back to
        picks = [['song.mp3'], None]
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as pick_files, \
                mock.patch('dirdelta.picker.pick_option', return_value=NO) as pick_option:
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(REMOVE)
        self.assertEqual(pick_files.call_args.args[0], 'cloud/mein')
        self.assertIn('from cloud/mein', pick_files.call_args.kwargs['header'])
        header = pick_option.call_args.kwargs['header'].splitlines()
        self.assertEqual(header[0], 'Remove 1 files from cloud/mein?')

if __name__ == '__main__':
    unittest.main()
