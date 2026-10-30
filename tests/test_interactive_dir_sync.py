import contextlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import clouddirtree
from dirdelta import dirtree
from dirdelta import elsewhere
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree
from dirdelta import picker
from dirdelta import replicalog

Sync = interactive_dir_sync.InteractiveDirSync
YES = Sync.CONFIRM_YES
NO = Sync.CONFIRM_NO
SURE = Sync.CONFIRM_SURE
NOTHING = Sync.NOTHING


class InteractiveDirSyncTest(unittest.TestCase):
    """src has a.txt, sub/b.txt and sub/c.txt, dst has only a.txt, so sub/b.txt and sub/c.txt are
    missing."""

    def setUp(self):
        self.src_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-sync-src-'))
        self.dst_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-sync-dst-'))
        helpers.make_files(self.src_root, ['a.txt', 'sub/b.txt', 'sub/c.txt'])
        helpers.make_files(self.dst_root, ['a.txt'])
        self.messages = []
        for patcher in (mock.patch('dirdelta.messages.print_line',
                                   side_effect=lambda s, *a: self.messages.append(s)),
                        mock.patch('dirdelta.messages.show')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.src_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.dst_root, ignore_errors=True)

    def _browse(self, picks, answers, src=None, dst=None, changes=None):
        """Browse src's files that dst lacks (by default, the local dirs', unscanned as dirsync_main
        leaves them), the file picker answering picks in turn (see helpers.scripted_files_picker),
        and the menus answers (see helpers.answering_option_picker). Returns the sync."""
        src = src or localdiskdirtree.LocalDiskDirTree(self.src_root, True)
        dst = dst or localdiskdirtree.LocalDiskDirTree(self.dst_root, True)
        picks = list(picks)
        self.sync = Sync(src, dst, changes=changes)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option:
            self.sync.browse()
        return self.sync

    def _exists(self, root, relpath):
        return os.path.exists(os.path.join(root, relpath))

    def _offered(self):
        """The files each file picker offered, and what was picked in it at first"""
        return [(call.args[1], call.kwargs['picked']) for call in self.pick_files.call_args_list]

    def test_copy_copies_and_goes_back_to_the_files_left(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([picker.Picked('', 'sub/b.txt', ['sub/b.txt']), None], ['Copy', YES])
        with open(os.path.join(self.dst_root, 'sub/b.txt')) as f:
            self.assertEqual(f.read(), 'sub/b.txt')
        self.assertFalse(self._exists(self.dst_root, 'sub/c.txt'))
        # Back where it was (the dir, as the file's gone), with the file left, nothing picked
        self.assertEqual(self._offered()[1], (['sub/c.txt'], []))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'sub')
        self.assertTrue(self.sync.has_changed)
        self.assertIn('Copy complete: copied 1 of 1 files to %s' % (self.dst_root,), self.messages)

    def test_live_changes_are_noted_for_the_replicas_logs(self):
        changes = replicalog.Changes()
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], ['sub/c.txt'], None], ['Copy', YES, 'Remove', YES, SURE], changes=changes)
        self.assertEqual(changes.summary(self.dst_root), "copied 1 file from %s" % (self.src_root,))
        self.assertEqual(changes.summary(self.src_root), "removed 1 file")
        # Not in a dry run
        changes = replicalog.Changes()
        self._browse([['sub/b.txt'], None], ['Copy', YES], changes=changes)
        self.assertEqual(changes.paths(), [])

    def test_the_other_picks_stay_picked(self):
        # Both picked, but only one copied: the other's copy fails
        real_copy = localdiskdirtree.shutil.copy2

        def copy(src, dst):
            if src.endswith('c.txt'):
                raise OSError('disk full')
            real_copy(src, dst)
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.shutil.copy2', side_effect=copy):
            self._browse([['sub/b.txt', 'sub/c.txt'], None], ['Copy', YES])
        self.assertEqual(self._offered()[1], (['sub/c.txt'], ['sub/c.txt']))

    def test_dry_run_copy_changes_nothing_and_drops_the_picks(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._browse([['sub/b.txt', 'sub/c.txt'], None], ['Copy', YES])
        self.assertFalse(self._exists(self.dst_root, 'sub'))
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], []))
        self.assertFalse(self.sync.has_changed)
        self.assertIn('Dry run, not copying sub/b.txt (1 out of 2)', self.messages)

    def test_copy_report_ends_saying_its_complete(self):
        last_lines = []

        @contextlib.contextmanager
        def progress_screen(title, label=None):
            yield
            last_lines.append(self.messages[-1])

        with mock.patch('dirdelta.messages.progress_screen', progress_screen):
            self._browse([['sub/b.txt'], None], ['Copy', YES])
        self.assertEqual(len(last_lines), 1)
        self.assertTrue(last_lines[0].startswith('Dry run complete: nothing was copied to'), last_lines)

    def test_picked_files_are_copied_from_src(self):
        # Their entries are made from the picked relpaths only
        copied = []
        with mock.patch('dirdelta.localdiskdirtree.LocalDiskDirTree.copy_inner_entries_from_dirtree',
                        side_effect=lambda tree, source: copied.extend(tree.iter_files())):
            self._browse([['sub/b.txt'], None], ['Copy', YES])
        self.assertEqual([(entry.relpath, entry.full_filesystem_path()) for entry in copied],
                         [('sub/b.txt', os.path.join(self.src_root, 'sub/b.txt'))])

    def test_remove_is_confirmed_twice_then_removes(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], None], ['Remove', YES, SURE])
        self.assertFalse(self._exists(self.src_root, 'sub/b.txt'))
        self.assertEqual(self._offered()[1], (['sub/c.txt'], []))
        self.assertIn('Remove complete: removed 1 of 1 files from %s' % (self.src_root,), self.messages)
        # The second time: are you sure, No first
        options = self.pick_option.call_args_list[2].args[0]
        self.assertEqual(options, [NO, SURE])
        self.assertIn('Are you sure? 1 file will be removed from %s, for good.' % (self.src_root,),
                      self.pick_option.call_args_list[2].kwargs['header'])

    def test_no_to_are_you_sure_removes_nothing_and_keeps_the_picks(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], None], ['Remove', YES, NO])
        self.assertTrue(self._exists(self.src_root, 'sub/b.txt'))
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt']))
        self.assertFalse(self.sync.has_changed)

    def test_dry_run_remove_leaves_disk_untouched(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._browse([['sub/b.txt'], None], ['Remove', YES, SURE])
        self.assertTrue(self._exists(self.src_root, 'sub/b.txt'))
        self.assertIn('Dry run, not removing sub/b.txt (1 out of 1)', self.messages)

    def test_the_action_menu_starts_with_nothing_which_goes_back_to_the_picks(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([picker.Picked('', 'sub/c.txt', ['sub/b.txt']), None], [NOTHING])
        options = self.pick_option.call_args_list[0].args[0]
        self.assertEqual(options[0], NOTHING)
        self.assertEqual([option.split(' ')[0] for option in options[1:]],
                         ['Copy', 'Remove', 'Rename', 'Rename'])
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt']))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'sub/c.txt')

    def test_quitting_the_menu_or_a_confirmation_is_nothing(self):
        for answers in ([None], ['Copy', None], ['Copy', NO]):
            with mock.patch('dirdelta.dryrun.DRYRUN', False):
                self._browse([['sub/b.txt'], None], answers)
            self.assertFalse(self._exists(self.dst_root, 'sub'))
            self.assertEqual(self._offered()[1][1], ['sub/b.txt'])

    def test_the_confirmation_starts_with_no_and_says_what_it_will_do(self):
        self._browse([['sub/b.txt'], None], ['Copy', NO])
        options = self.pick_option.call_args.args[0]
        self.assertEqual(options[0], NO)
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        self.assertEqual(header[0], 'Copy 1 file from %s to %s?' % (self.src_root, self.dst_root))
        self.assertEqual(header[1], '  sub/b.txt')
        self.assertIn('dry run', header[-1])
        self.assertEqual(self.pick_option.call_args.kwargs['label'], ('COPY', 'blue'))

    def disabled(self):
        """The action menu's disabled options' texts"""
        shown = self.pick_option.call_args_list[0].kwargs['shown_as']()
        return [text.text for text in shown.values()]

    def test_what_cant_be_done_is_greyed_out(self):
        # A read-only dst, and nothing has a match in it to rename
        real_access = os.access
        with mock.patch('dirdelta.interactive_dir_sync.os.access',
                        side_effect=lambda path, mode: path != self.dst_root and real_access(path, mode)):
            self._browse([['sub/b.txt'], None], [NOTHING])
        texts = sorted(self.disabled())
        self.assertEqual(len(texts), 3)
        self.assertEqual(texts[0], "Copy the 1 file to %s: can't: it's read-only" % (self.dst_root,))
        self.assertEqual(texts[1], "Rename 0 files of these to their matches' paths, in %s: none of "
                                   "these may be there, moved or renamed" % (self.src_root,))
        self.assertEqual(texts[2], "Rename the files matching 0 of these to these paths, in %s: can't: "
                                   "it's read-only" % (self.dst_root,))

    def test_two_cloud_replicas_cant_copy(self):
        src = clouddirtree.CloudDirTree('cloud/a')
        src.add_file_by_relpath('x')
        self._browse([['x'], None], [NOTHING], src, clouddirtree.CloudDirTree('cloud/b'))
        self.assertIn("Copy the 1 file to cloud/b: can't: both are Google Drive's", self.disabled())

    def test_nothing_missing_says_so_without_a_picker(self):
        helpers.make_files(self.dst_root, ['sub/b.txt', 'sub/c.txt'])
        self._browse([], [])
        title, lines, _ = interactive_dir_sync.messages.show.call_args.args
        self.assertEqual(title, 'Nothing to do')
        self.assertEqual(lines, ["%s has all of %s's files." % (self.dst_root, self.src_root)])

    def test_after_the_last_ones_are_done_it_says_so_and_ends(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt', 'sub/c.txt']], ['Copy', YES])
        self.assertEqual(interactive_dir_sync.messages.show.call_args.args[0], 'Nothing to do')

    def test_trees_other_than_two_local_dirs_are_diffed_as_they_are(self):
        # (A cloud tree, say.) Sorted by path components, so each dir's files stay together.
        src = dirtree.DirTree('/src')
        for relpath in ['b/2.txt', 'a b/1.txt', 'a/1.txt', 'c.txt']:
            src.add_file_by_relpath(relpath)
        dst = dirtree.DirTree('/dst')
        dst.add_file_by_relpath('c.txt')
        self._browse([None], [], src, dst)
        self.assertEqual(self._offered()[0][0], ['a/1.txt', 'a b/1.txt', 'b/2.txt'])

    def test_the_picker_shows_where_dst_has_files_of_the_same_names(self):
        # sub/b.txt moved to elsewhere/b.txt in dst
        helpers.make_files(self.dst_root, ['elsewhere/b.txt'])
        self._browse([None], [])
        # The picker calls it, with a send() for what's found
        sent = {}
        self.pick_files.call_args.kwargs['previews'](lambda found=None, default=None: sent.update(found or {}))
        self.assertEqual(sorted(sent), ['sub/b.txt', 'sub/c.txt'])
        lines = sent['sub/b.txt']
        self.assertEqual(lines[lines.index("  elsewhere/") + 1], "    b.txt  15 B")

    def test_the_selected_files_contents_are_compared_and_kept(self):
        helpers.make_files(self.dst_root, ['elsewhere/b.txt'])
        self._browse([None], [])
        on_selection = self.pick_files.call_args.kwargs['on_selection']
        self.assertIs(on_selection.args[4], self.sync.checked)
        self.assertIs(on_selection.args[3], self.sync.dst_index)

    def test_a_cloud_replica_is_named_as_a_cloud_path(self):
        # Not by its path in Drive (/mein), which reads like a local dir
        src = clouddirtree.CloudDirTree('cloud/mein')
        src.add_file_by_relpath('song.mp3')
        self._browse([['song.mp3'], None], ['Remove', NO], src, dirtree.DirTree('/local'))
        self.assertEqual(self.pick_files.call_args.args[0], 'cloud/mein')
        self.assertIn('Files in cloud/mein', self.pick_files.call_args.kwargs['header'])
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        self.assertEqual(header[0], 'Remove 1 file from cloud/mein?')


class RenameTest(unittest.TestCase):
    """src has photos/x.jpg, which dst has at old/x.jpg (the same size): moved there; and
    photos/y.jpg, which dst lacks"""

    def setUp(self):
        self.src_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-rename-src-'))
        self.dst_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-rename-dst-'))
        for root, relpath in ((self.src_root, 'photos/x.jpg'), (self.dst_root, 'old/x.jpg'),
                              (self.src_root, 'photos/y.jpg')):
            os.makedirs(os.path.dirname(os.path.join(root, relpath)), exist_ok=True)
            with open(os.path.join(root, relpath), 'w') as f:
                f.write('the photo')
        for patcher in (mock.patch('dirdelta.messages.print_line'), mock.patch('dirdelta.messages.show')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.src_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.dst_root, ignore_errors=True)

    def browse(self, answers, is_dry_run=False):
        self.src = localdiskdirtree.LocalDiskDirTree(self.src_root, True)
        self.dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, True)
        self.dst_index = elsewhere.Index(self.dst)
        self.src_index = elsewhere.Index(self.src)
        self.src_index.build()
        picks = [['photos/x.jpg', 'photos/y.jpg'], None]
        sync = Sync(self.src, self.dst, src_index=self.src_index, dst_index=self.dst_index)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option, \
                mock.patch('dirdelta.dryrun.DRYRUN', is_dry_run):
            sync.browse()
        return sync

    def test_rename_in_dst_moves_its_match_to_the_files_path(self):
        sync = self.browse(['Rename the', YES])
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'photos/x.jpg')))
        # Its dir, left empty, is gone too
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'old')))
        self.assertEqual(self.dst_index.files_named('x.jpg'), {'photos/x.jpg': 9})
        self.assertTrue(sync.has_changed)
        # Only y.jpg is left, still picked (x.jpg was done)
        self.assertEqual(self.pick_files.call_args.args[1], ['photos/y.jpg'])
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['photos/y.jpg'])
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        # old/ has only it: moved as one
        self.assertEqual(header[:2], ['Move 1 file in %s?' % (self.dst_root,),
                                      '  old/ -> photos/ (a dir, with its 1 file, moved as one)'])
        self.assertEqual(self.pick_option.call_args.kwargs['label'], ('RENAME', 'cyan'))

    def test_rename_in_src_moves_the_file_to_its_matchs_path(self):
        self.browse(['Rename 1 file of these', YES])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'old/x.jpg')))
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'photos/x.jpg')))
        self.assertEqual(self.src_index.files_named('x.jpg'), {'old/x.jpg': 9})

    def test_the_menu_counts_the_files_with_a_sure_match(self):
        self.browse([NOTHING])
        options = self.pick_option.call_args.args[0]
        self.assertIn("Rename the files matching 1 of these to these paths, in %s" % (self.dst_root,), options)
        self.assertIn("Rename 1 file of these to their matches' paths, in %s" % (self.src_root,), options)

    def test_a_renamed_file_is_compared_then_renamed(self):
        # dst has big.mov as clip.mov, and another file of its size
        big = b'x' * elsewhere.RENAMED_MIN_SIZE
        for root, relpath, contents in ((self.src_root, 'videos/big.mov', big),
                                        (self.dst_root, 'v/clip.mov', big),
                                        (self.dst_root, 'v/other.mov', b'y' * len(big))):
            os.makedirs(os.path.dirname(os.path.join(root, relpath)), exist_ok=True)
            with open(os.path.join(root, relpath), 'wb') as f:
                f.write(contents)
        self.src = localdiskdirtree.LocalDiskDirTree(self.src_root, True)
        self.dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, True)
        sync = Sync(self.src, self.dst)
        picks = [['videos/big.mov'], None]
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)), \
                helpers.answering_option_picker(['Rename the', YES]) as self.pick_option, \
                mock.patch('dirdelta.dryrun.DRYRUN', False):
            sync.browse()
        self.assertEqual(sync.checked['videos/big.mov'], {'v/clip.mov': True, 'v/other.mov': False})
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'videos/big.mov')))
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'v/other.mov')))
        self.assertIn('  v/clip.mov -> videos/big.mov', self.pick_option.call_args.kwargs['header'])

    def test_a_rename_with_none_surely_there_after_comparing_says_so(self):
        with open(os.path.join(self.dst_root, 'old/x.jpg'), 'w') as f:
            f.write('another!!')
        self.browse(['Rename the'])
        self.assertEqual(interactive_dir_sync.messages.show.call_args.args[0], 'Nothing to rename')
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'old/x.jpg')))

    def test_a_dry_run_moves_nothing(self):
        sync = self.browse(['Rename the', YES], is_dry_run=True)
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'old/x.jpg')))
        self.assertFalse(sync.has_changed)
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['photos/y.jpg'])

    def test_no_moves_nothing(self):
        self.browse(['Rename the', NO])
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'old/x.jpg')))


class RefreshKeyTest(unittest.TestCase):
    """The file picker's key that reads the selected folder anew from Drive"""
    def setUp(self):
        self.cloud = clouddirtree.CloudDirTree('cloud/mein')
        for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
            self.cloud.add_file_by_relpath(relpath)
        self.local = dirtree.DirTree('/local')
        for patcher in (mock.patch('dirdelta.messages.show'),
                        mock.patch('dirdelta.picker.pick_option', return_value=NOTHING)):
            self.addCleanup(patcher.stop)
            patcher.start()
        self.show = interactive_dir_sync.messages.show

    def browse(self, src, dst, answers, refresh=None):
        """Browse, the file picker answering answers in turn; returns pick_files's calls"""
        with mock.patch('dirdelta.picker.pick_files', side_effect=answers) as pick_files, \
                mock.patch.object(clouddirtree.CloudDirTree, 'refresh_from_drive', autospec=True,
                                  side_effect=refresh) as self.refresh:
            self.sync = Sync(src, dst, checked={'a/1.mp3': {'x': True}})
            self.sync.src_index.build()
            self.sync.browse()
        return pick_files.call_args_list

    def test_the_key_refreshes_the_selected_folder_and_picks_again_where_it_was(self):
        def refresh(tree, relpath):
            # Since the cache was made, a/2.mp3 went from Drive
            tree.remove_node('a/2.mp3')
        calls = self.browse(self.cloud, self.local,
                            [picker.Picked('r', 'a', ['a/1.mp3', 'a/2.mp3']), None], refresh)
        self.refresh.assert_called_once_with(self.cloud, 'a')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(self.sync.checked, {})
        # Its files by name are listed again, when they're next needed
        self.assertFalse(self.sync.src_index.is_built())
        self.assertEqual(calls[0].kwargs['keys'], 'r')
        self.assertIn('r: read the selected folder anew from Google Drive', calls[0].kwargs['header'])
        self.assertIsNone(calls[0].kwargs['selected'])
        # What's still missing, what's still picked of it, where it was
        self.assertEqual(calls[1].args[1], ['a/1.mp3', 'b/3.mp3'])
        self.assertEqual(calls[1].kwargs['picked'], ['a/1.mp3'])
        self.assertEqual(calls[1].kwargs['selected'], 'a')

    def test_the_other_replica_is_refreshed_when_its_drives(self):
        self.local.add_file_by_relpath('x/new.mp3')
        self.browse(self.local, self.cloud, [picker.Picked('r', 'x/new.mp3', []), None])
        self.refresh.assert_called_once_with(self.cloud, 'x/new.mp3')

    def test_without_a_drive_replica_theres_no_key(self):
        other = dirtree.DirTree('/other')
        other.add_file_by_relpath('a.mp3')
        calls = self.browse(other, self.local, [None])
        self.assertEqual(calls[0].kwargs['keys'], '')
        self.assertNotIn('Google Drive', calls[0].kwargs['header'])
        self.assertFalse(self.sync.has_changed)

    def test_a_refresh_with_nothing_left_missing_says_so(self):
        def refresh(tree, relpath):
            for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
                tree.remove_node(relpath)
        calls = self.browse(self.cloud, self.local, [picker.Picked('r', '', [])], refresh)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.show.call_args.args[0], 'Nothing to do')

    def test_a_failed_refresh_says_why_and_picks_again(self):
        calls = self.browse(self.cloud, self.local,
                            [picker.Picked('r', 'a', ['b/3.mp3']), None], OSError('no network'))
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Refresh cloud/mein/a from Google Drive')
        self.assertEqual(lines, ["Couldn't refresh it: no network"])
        self.assertFalse(self.sync.has_changed)
        self.assertEqual(calls[1].kwargs['picked'], ['b/3.mp3'])


class ShownTest(unittest.TestCase):
    def test_the_selection_or_the_closest_dir_still_shown(self):
        missing = ['a/b/1', 'a/c/2']
        self.assertEqual(interactive_dir_sync._shown('a/b/1', missing), 'a/b/1')
        self.assertEqual(interactive_dir_sync._shown('a/b', missing), 'a/b')
        self.assertEqual(interactive_dir_sync._shown('a/d/3', missing), 'a')
        self.assertEqual(interactive_dir_sync._shown('z', missing), '')


if __name__ == '__main__':
    unittest.main()
