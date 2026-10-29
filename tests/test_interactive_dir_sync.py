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

    def test_the_picker_and_confirmation_are_labeled_with_the_action(self):
        for action, label in ((COPY, ('COPY', 'blue')), (REMOVE, ('REMOVE', 'magenta'))):
            src = dirtree.DirTree('/src')
            src.add_file_by_relpath('a.txt')
            dst = dirtree.DirTree('/dst')
            # No, then quitting the picker it goes back to
            picks = [['a.txt'], None]
            with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as pick_files, \
                    mock.patch('dirdelta.picker.pick_option', return_value=NO) as pick_option:
                interactive_dir_sync.InteractiveDirSync(src, dst).sync(action)
            self.assertEqual(pick_files.call_args.kwargs['label'], label)
            self.assertEqual(pick_option.call_args.kwargs['label'], label)

    def test_the_picker_shows_where_dst_has_files_of_the_same_names(self):
        # sub/b.txt moved to elsewhere/b.txt in dst
        helpers.make_files(self.dst_root, ['elsewhere/b.txt'])
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, True)
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, True)
        with helpers.scripted_files_picker(lambda relpaths: None) as pick_files:
            interactive_dir_sync.InteractiveDirSync(src, dst).sync(COPY)
        previews = pick_files.call_args.kwargs['previews']
        self.assertEqual(list(previews), ['sub/b.txt'])
        self.assertEqual(previews['sub/b.txt'][:3],
                         ["In %s:" % (dst.displayname(),), "  elsewhere/",
                          "    b.txt  15 B"])

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


class RefreshKeyTest(unittest.TestCase):
    """The file picker's key that reads the selected folder anew from Drive"""
    def setUp(self):
        self.cloud = clouddirtree.CloudDirTree('cloud/mein')
        for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
            self.cloud.add_file_by_relpath(relpath)
        self.local = dirtree.DirTree('/local')
        for patcher in (mock.patch('dirdelta.messages.print_line'),
                        mock.patch('dirdelta.messages.show'),
                        mock.patch('dirdelta.picker.pick_option', return_value=NO)):
            self.addCleanup(patcher.stop)
            self.show = patcher.start()
        self.show = interactive_dir_sync.messages.show

    def sync(self, src, dst, answers, refresh=None):
        """Remove files from src, the file picker answering answers in turn; returns pick_files's
        calls"""
        with mock.patch('dirdelta.picker.pick_files', side_effect=answers) as pick_files, \
                mock.patch.object(clouddirtree.CloudDirTree, 'refresh_from_drive', autospec=True,
                                  side_effect=refresh) as self.refresh:
            sync = interactive_dir_sync.InteractiveDirSync(src, dst)
            sync.sync(REMOVE)
        self.was_refreshed = sync.was_refreshed
        return pick_files.call_args_list

    def test_the_key_refreshes_the_selected_folder_and_picks_again_where_it_was(self):
        def refresh(tree, relpath):
            # Since the cache was made, a/2.mp3 went from Drive
            tree.remove_node('a/2.mp3')
        calls = self.sync(self.cloud, self.local,
                          [interactive_dir_sync.picker.KeyPressed('r', 'a', ['a/1.mp3', 'a/2.mp3']), None],
                          refresh)
        self.refresh.assert_called_once_with(self.cloud, 'a')
        self.assertTrue(self.was_refreshed)
        self.assertEqual(calls[0].kwargs['keys'], 'r')
        self.assertIn('r: read the selected folder anew from Google Drive', calls[0].kwargs['header'])
        self.assertIsNone(calls[0].kwargs['selected'])
        # What's still missing, what's still picked of it, where it was
        self.assertEqual(calls[1].args[1], ['a/1.mp3', 'b/3.mp3'])
        self.assertEqual(calls[1].kwargs['picked'], ['a/1.mp3'])
        self.assertEqual(calls[1].kwargs['selected'], 'a')

    def test_the_other_replica_is_refreshed_when_its_drives(self):
        self.local.add_file_by_relpath('x/new.mp3')
        self.sync(self.local, self.cloud,
                  [interactive_dir_sync.picker.KeyPressed('r', 'x/new.mp3', []), None])
        self.refresh.assert_called_once_with(self.cloud, 'x/new.mp3')

    def test_without_a_drive_replica_theres_no_key(self):
        other = dirtree.DirTree('/other')
        other.add_file_by_relpath('a.mp3')
        calls = self.sync(other, self.local, [None])
        self.assertEqual(calls[0].kwargs['keys'], '')
        self.assertNotIn('Google Drive', calls[0].kwargs['header'])
        self.assertFalse(self.was_refreshed)

    def test_a_refresh_with_nothing_left_missing_says_so(self):
        def refresh(tree, relpath):
            for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
                tree.remove_node(relpath)
        calls = self.sync(self.cloud, self.local,
                          [interactive_dir_sync.picker.KeyPressed('r', '', [])], refresh)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.show.call_args.args[0], 'Nothing to remove')

    def test_a_failed_refresh_says_why_and_picks_again(self):
        calls = self.sync(self.cloud, self.local,
                          [interactive_dir_sync.picker.KeyPressed('r', 'a', ['b/3.mp3']), None],
                          OSError('no network'))
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Refresh cloud/mein/a from Google Drive')
        self.assertEqual(lines, ["Couldn't refresh it: no network"])
        self.assertFalse(self.was_refreshed)
        self.assertEqual(calls[1].kwargs['picked'], ['b/3.mp3'])


if __name__ == '__main__':
    unittest.main()
