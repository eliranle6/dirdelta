import contextlib
import os
import shutil
import tempfile
import unittest
import zipfile
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

    def exists(self, root, relpath):
        return os.path.exists(os.path.join(root, relpath))

    def _offered(self):
        """The files each file picker offered, and what was picked in it at first"""
        return [(call.args[1], call.kwargs['picked']) for call in self.pick_files.call_args_list]

    def test_copy_copies_and_goes_back_to_the_files_left(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([picker.Picked('', 'sub/b.txt', ['sub/b.txt']), None], ['Copy', YES])
        with open(os.path.join(self.dst_root, 'sub/b.txt')) as f:
            self.assertEqual(f.read(), 'sub/b.txt')
        self.assertFalse(self.exists(self.dst_root, 'sub/c.txt'))
        # Back where it was (on the next file, as the file's gone), with the file left, nothing picked
        self.assertEqual(self._offered()[1], (['sub/c.txt'], []))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'sub/c.txt')
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
        self.assertFalse(self.exists(self.dst_root, 'sub'))
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
        with mock.patch('dirdelta.localdiskdirtree.LocalDiskDirTree.copy_in',
                        side_effect=lambda files, source: copied.extend(files)):
            self._browse([['sub/b.txt'], None], ['Copy', YES])
        self.assertEqual([(entry.relpath, entry.full_filesystem_path()) for entry in copied],
                         [('sub/b.txt', os.path.join(self.src_root, 'sub/b.txt'))])

    def test_remove_is_confirmed_twice_then_removes(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], None], ['Remove', YES, SURE])
        self.assertFalse(self.exists(self.src_root, 'sub/b.txt'))
        self.assertEqual(self._offered()[1], (['sub/c.txt'], []))
        self.assertIn('Remove complete: removed 1 of 1 files from %s' % (self.src_root,), self.messages)
        # The second time: are you sure, No first
        options = helpers.labels_of(self.pick_option.call_args_list[2].args[0])
        self.assertEqual(options, [NO, SURE])
        self.assertIn('Are you sure? 1 file will be removed from %s, for good.' % (self.src_root,),
                      self.pick_option.call_args_list[2].kwargs['header'])

    def test_no_to_are_you_sure_removes_nothing_and_keeps_the_picks(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], None], ['Remove', YES, NO])
        self.assertTrue(self.exists(self.src_root, 'sub/b.txt'))
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt']))
        self.assertFalse(self.sync.has_changed)

    def test_dry_run_remove_leaves_disk_untouched(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._browse([['sub/b.txt'], None], ['Remove', YES, SURE])
        self.assertTrue(self.exists(self.src_root, 'sub/b.txt'))
        self.assertIn('Dry run, not removing sub/b.txt (1 out of 1)', self.messages)

    def test_the_action_menu_starts_with_nothing_which_goes_back_to_the_picks(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._browse([picker.Picked('', 'sub/c.txt', ['sub/b.txt']), None], [NOTHING])
        options = [picker.option_label(option) for option in self.pick_option.call_args_list[0].args[0]]
        self.assertEqual(options[0], NOTHING)
        # Each kind apart, after a blank line
        self.assertEqual([option.split(' ')[0] for option in options[1:]],
                         ['', 'Ask', '', 'Copy', '', 'Remove', '', 'Rename', 'Rename', '', 'Open'])
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt']))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'sub/c.txt')

    def test_ctrl_x_opens_the_selected_file(self):
        with mock.patch('dirdelta.opening.Opener.open_in_background') as open_in_background:
            self._browse([None], [])
            kwargs = self.pick_files.call_args.kwargs
            self.assertEqual(kwargs['notify_keys'], '\x18')
            self.assertIn("  %-17s%s" % ('Ctrl-X', 'open'), kwargs['help_lines'])
            kwargs['on_notify']('\x18', 'sub/c.txt', [])
            kwargs['on_notify']('\x18', 'sub/c.txt', ['sub/b.txt', 'sub/c.txt'])
        files = {'sub/b.txt', 'sub/c.txt'}
        # Not the picked ones: the menu's Open opens them
        self.assertEqual(open_in_background.call_args_list, [mock.call(['sub/c.txt'], files)] * 2)

    def test_what_opening_says_is_on_the_bottom_line(self):
        self._browse([None], [])
        shown_as = self.pick_files.call_args.kwargs['shown_as']
        with mock.patch('dirdelta.opening.subprocess.Popen') as popen:
            self.sync._opener.open(['sub/b.txt'], ['sub/b.txt'])
        self.assertEqual(popen.call_args.args[0], ['xdg-open', os.path.join(self.src_root, 'sub', 'b.txt')])
        self.assertIn('Opened b.txt', shown_as()[''])

    def test_open_in_the_menu_opens_the_picked_files_and_goes_back_to_them(self):
        with mock.patch('dirdelta.opening.Opener.open_in_background') as open_in_background:
            self._browse([picker.Picked('', 'sub', ['sub/b.txt', 'sub/c.txt']), None],
                         ['Open the 2 files with their programs'])
        open_in_background.assert_called_once_with(['sub/b.txt', 'sub/c.txt'], ['sub/b.txt', 'sub/c.txt'])
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt', 'sub/c.txt']))

    def test_quitting_the_menu_or_a_confirmation_is_nothing(self):
        for answers in ([None], ['Copy', None], ['Copy', NO]):
            with mock.patch('dirdelta.dryrun.DRYRUN', False):
                self._browse([['sub/b.txt'], None], answers)
            self.assertFalse(self.exists(self.dst_root, 'sub'))
            self.assertEqual(self._offered()[1][1], ['sub/b.txt'])

    def test_the_confirmation_starts_with_no_and_says_what_it_will_do(self):
        self._browse([['sub/b.txt'], None], ['Copy', NO])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertEqual(options[0], NO)
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        self.assertEqual(header[0], 'Copy 1 file from %s to %s?' % (self.src_root, self.dst_root))
        self.assertEqual(header[1], '  sub/b.txt')
        self.assertIn('dry run', header[-1])
        self.assertEqual(self.pick_option.call_args.kwargs['label'], ('COPY', 'blue'))

    def disabled(self):
        """The action menu's disabled options' texts (after the shortcuts' column)"""
        shown = helpers.shown_of(self.pick_option.call_args_list[0].args[0])
        return [text.text.lstrip() for text in shown.values() if isinstance(text, picker.Disabled)]

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

    def test_cc_renames_the_selected_file_and_diffs_anew(self):
        with mock.patch('dirdelta.messages.ask', return_value='a.txt'), mock.patch('dirdelta.dryrun.DRYRUN', False):
            # sub/b.txt renamed to a.txt there: still missing (dst has a.txt, not sub/a.txt)
            self._browse([picker.Picked('cc', 'sub/b.txt', ['sub/b.txt']), None], [])
        self.assertTrue(self.exists(self.src_root, 'sub/a.txt'))
        kwargs = self.pick_files.call_args.kwargs
        self.assertEqual(self.pick_files.call_args.args[1], ['sub/a.txt', 'sub/c.txt'])
        self.assertEqual(kwargs['selected'], 'sub/a.txt')
        self.assertEqual(kwargs['picked'], ['sub/a.txt'])

    def test_after_a_copy_the_replicas_arent_diffed_anew(self):
        real = interactive_dir_sync.find_missing
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.interactive_dir_sync.find_missing', side_effect=real) as find_missing:
            self._browse([picker.Picked('', 'sub/b.txt', ['sub/b.txt']), None], ['Copy', YES])
        find_missing.assert_called_once()
        self.assertEqual(self._offered()[1][0], ['sub/c.txt'])

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
        with mock.patch('dirdelta.drivecache.user', return_value='me'):
            self._browse([['song.mp3'], None], ['Remove', NO], src, dirtree.DirTree('/local'))
        self.assertEqual(self.pick_files.call_args.args[0], 'Cloud(me):/mein')
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
        options = helpers.labels_of(self.pick_option.call_args.args[0])
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
                            [picker.Picked(Sync.REFRESH_KEY, 'a', ['a/1.mp3', 'a/2.mp3']), None], refresh)
        self.refresh.assert_called_once_with(self.cloud, 'a')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(self.sync.checked, {})
        # Its files by name are listed again, when they're next needed
        self.assertFalse(self.sync.src_index.is_built())
        # And the replicas dashboard's
        self.assertEqual(calls[0].kwargs['keys'], Sync.REFRESH_KEY + '#a:e')
        self.assertIn("  %-17s%s" % ('Ctrl-R', 'read the folder anew from Drive, list the tree on the right anew'), calls[0].kwargs['help_lines'])
        self.assertIsNone(calls[0].kwargs['selected'])
        # What's still missing, what's still picked of it, where it was
        self.assertEqual(calls[1].args[1], ['a/1.mp3', 'b/3.mp3'])
        self.assertEqual(calls[1].kwargs['picked'], ['a/1.mp3'])
        self.assertEqual(calls[1].kwargs['selected'], 'a')

    def test_read_anew_in_the_menu_refreshes_the_selected_files_folder(self):
        with helpers.answering_option_picker(['Read cloud/mein/a/ anew from Google Drive']) as pick_option:
            calls = self.browse(self.cloud, self.local,
                                [picker.Picked('', 'a/2.mp3', ['a/1.mp3']), None])
        self.refresh.assert_called_once_with(self.cloud, 'a/2.mp3')
        self.assertEqual(helpers.labels_of(pick_option.call_args.args[0])[-1], 'Read cloud/mein/a/ anew from Google Drive')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(calls[1].kwargs['picked'], ['a/1.mp3'])
        self.assertEqual(calls[1].kwargs['selected'], 'a/2.mp3')

    def test_read_anew_isnt_offered_without_drive(self):
        local = dirtree.DirTree('/other')
        local.add_file_by_relpath('x.mp3')
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            self.browse(local, self.local, [picker.Picked('', 'x.mp3', ['x.mp3']), None])
        self.assertFalse(any(option.startswith('Read') for option in helpers.labels_of(pick_option.call_args.args[0])))

    def test_the_other_replica_is_refreshed_when_its_drives(self):
        self.local.add_file_by_relpath('x/new.mp3')
        self.browse(self.local, self.cloud, [picker.Picked(Sync.REFRESH_KEY, 'x/new.mp3', []), None])
        self.refresh.assert_called_once_with(self.cloud, 'x/new.mp3')

    def test_the_side_tree_is_listed_anew_and_is_gone_back_to_after_the_key_there(self):
        other = dirtree.DirTree('/other')
        other.add_file_by_relpath('a.mp3')
        with mock.patch('dirdelta.sidetree._listed', return_value=([], [])) as listed:
            calls = self.browse(other, self.local, [picker.Picked(Sync.REFRESH_KEY, 'a.mp3', ['a.mp3']),
                                                    picker.Picked(picker.SIDE_KEY, 'a.mp3', ['a.mp3'], 'x', Sync.REFRESH_KEY),
                                                    picker.Picked('', 'a.mp3', ['a.mp3']), None])
        # Once to start with, once for each Ctrl-R, not for another return to the picker
        self.assertEqual(listed.call_count, 3)
        self.assertEqual(len(calls), 4)
        self.refresh.assert_not_called()
        self.assertEqual(calls[0].kwargs['keys'], Sync.REFRESH_KEY + '#a:e')
        self.assertIn(Sync.REFRESH_KEY, calls[0].kwargs['side'].keys)
        self.assertEqual(calls[1].kwargs['picked'], ['a.mp3'])
        # After the key in the side tree, it's where the picker starts; only then
        self.assertEqual([call.kwargs['side'].start for call in calls], [None, None, 'x', None])

    def test_the_key_in_the_side_tree_reads_whats_selected_there_only_in_dst(self):
        self.local.add_file_by_relpath('x/new.mp3')
        calls = self.browse(self.local, self.cloud,
                            [picker.Picked(picker.SIDE_KEY, 'x/new.mp3', [], 'b', Sync.REFRESH_KEY), None])
        self.refresh.assert_called_once_with(self.cloud, 'b')
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.sync.has_changed)

    def test_a_refresh_with_nothing_left_missing_says_so(self):
        def refresh(tree, relpath):
            for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
                tree.remove_node(relpath)
        calls = self.browse(self.cloud, self.local, [picker.Picked(Sync.REFRESH_KEY, '', [])], refresh)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.show.call_args.args[0], 'Nothing to do')

    def test_a_failed_refresh_says_why_and_picks_again(self):
        calls = self.browse(self.cloud, self.local,
                            [picker.Picked(Sync.REFRESH_KEY, 'a', ['b/3.mp3']), None], OSError('no network'))
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Refresh cloud/mein/a from Google Drive')
        self.assertEqual(lines, ["Couldn't refresh it: no network"])
        self.assertFalse(self.sync.has_changed)
        self.assertEqual(calls[1].kwargs['picked'], ['b/3.mp3'])


class _TwoDirsTestCase(unittest.TestCase):
    """A sync of two local dirs"""

    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-ask-'))
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.src_path, self.dst_path = os.path.join(self.tmpdir, 'src'), os.path.join(self.tmpdir, 'dst')
        helpers.make_files(self.src_path, ['a.txt', 'b.txt', 'c.txt'])
        helpers.make_files(self.dst_path, ['old/d.txt'])
        for patcher in (mock.patch('dirdelta.messages.print_line'), mock.patch('dirdelta.messages.print_progress'),
                        mock.patch('dirdelta.messages.show'), mock.patch('dirdelta.messages.ask', return_value='do it')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sync = Sync(localdiskdirtree.LocalDiskDirTree(self.src_path, silent=True),
                         localdiskdirtree.LocalDiskDirTree(self.dst_path, silent=True))


class ReadingLocalReplicasAnewTest(_TwoDirsTestCase):
    """Ctrl-R, for what changed outside dirdelta"""

    def press(self, chosen):
        """browse(), the key pressed as chosen says after dst got a.txt from outside dirdelta; returns
        pick_files's calls"""
        answers = [chosen, None]

        def pick_files(root, items, **kwargs):
            answer = answers.pop(0)
            if answer is not None:
                helpers.make_files(self.dst_path, ['a.txt'])
            return answer
        self.sync.src_index.build()
        self.sync.dst_index.build()
        self.sync.checked['a.txt'] = {'x': True}
        with mock.patch('dirdelta.picker.pick_files', side_effect=pick_files) as called:
            self.sync.browse()
        return called.call_args_list

    def test_what_each_lacks_is_found_anew(self):
        calls = self.press(picker.Picked(Sync.REFRESH_KEY, 'b.txt', ['a.txt', 'b.txt']))
        self.assertEqual(sorted(calls[1].args[1]), ['b.txt', 'c.txt'])
        self.assertEqual(calls[1].kwargs['picked'], ['b.txt'])
        self.assertEqual(calls[1].kwargs['selected'], 'b.txt')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(self.sync.checked, {})
        self.assertFalse(self.sync.src_index.is_built())
        self.assertFalse(self.sync.dst_index.is_built())
        self.assertIn('f a.txt', calls[1].kwargs['side'].items)

    def test_in_the_side_tree_only_dst_is_and_it_stays_there(self):
        calls = self.press(picker.Picked(picker.SIDE_KEY, 'b.txt', [], 'old/d.txt', Sync.REFRESH_KEY))
        self.assertEqual(sorted(calls[1].args[1]), ['b.txt', 'c.txt'])
        self.assertTrue(self.sync.src_index.is_built())
        self.assertFalse(self.sync.dst_index.is_built())
        self.assertEqual(calls[1].kwargs['side'].start, 'old/d.txt')


class AskAITest(_TwoDirsTestCase):
    """Asking the AI, with what it answers scripted"""

    def ask(self, steps, review=None, is_dry_run=False):
        """_ask_ai() of all src's files, the AI answering steps, the review answering review(items)
        (by default, leaving all picked), and every confirmation answered yes (the last option)"""
        def pick_files(root, items, **_):
            self.items = list(items)
            return (review or (lambda items: picker.Picked('', '', list(items))))(items)
        with mock.patch('dirdelta.ai._run_query', return_value={'summary': 'ok', 'steps': steps}) as query, \
                mock.patch('dirdelta.picker.pick_files', side_effect=pick_files), \
                mock.patch('dirdelta.picker.pick_option', side_effect=lambda options, **_: options[-1]), \
                mock.patch('dirdelta.dryrun.DRYRUN', is_dry_run), mock.patch.object(
                    localdiskdirtree.LocalDiskDirTree, 'trashing', return_value=contextlib.nullcontext()):
            self.query = query
            return self.sync._ask_ai(['a.txt', 'b.txt', 'c.txt'])

    def test_what_the_user_approves_is_done(self):
        done = self.ask([{'action': Sync.COPY, 'number': 1, 'reason': 'wanted'},
                         {'action': Sync.RENAME_IN_SRC, 'number': 2, 'path': 'new/b2.txt', 'reason': 'neater'},
                         {'action': Sync.RENAME_IN_DST, 'number': 4, 'path': 'moved/d.txt', 'reason': 'neater'},
                         {'action': Sync.REMOVE, 'number': 3, 'reason': 'junk'}])
        self.assertEqual(sorted(done), ['a.txt', 'b.txt', 'c.txt', 'moved/d.txt'])
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'a.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.src_path, 'new/b2.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'moved/d.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.src_path, 'c.txt')))
        self.assertIsNone(self.sync._last_action)

    def test_whats_unpicked_in_the_review_isnt_done(self):
        steps = [{'action': Sync.COPY, 'number': 1, 'reason': ''}, {'action': Sync.COPY, 'number': 2, 'reason': ''}]
        done = self.ask(steps, lambda items: picker.Picked('', '', ['Copy to destination/b.txt']))
        self.assertEqual(done, ['b.txt'])
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'a.txt')))

    def test_quitting_the_review_does_nothing(self):
        self.assertIsNone(self.ask([{'action': Sync.COPY, 'number': 1, 'reason': ''}], lambda items: None))
        self.assertEqual(sorted(os.listdir(self.dst_path)), ['old'])

    def test_a_dry_run_changes_nothing(self):
        done = self.ask([{'action': Sync.COPY, 'number': 1, 'reason': ''},
                         {'action': Sync.REMOVE, 'number': 2, 'reason': ''}], is_dry_run=True)
        self.assertEqual(sorted(done), ['a.txt', 'b.txt'])
        self.assertEqual(sorted(os.listdir(self.dst_path)), ['old'])
        self.assertTrue(os.path.exists(os.path.join(self.src_path, 'b.txt')))

    def test_a_target_thats_taken_isnt_offered(self):
        self.ask([{'action': Sync.RENAME_IN_SRC, 'number': 1, 'path': 'b.txt', 'reason': ''},
                  {'action': Sync.COPY, 'number': 3, 'reason': ''}])
        self.assertEqual(self.items, ['Copy to destination/c.txt'])

    def test_with_no_focus_it_reads_nothing(self):
        self.ask([{'action': Sync.COPY, 'number': 1, 'reason': ''}])
        prompt, readable_dirs = self.query.call_args.args[:2]
        self.assertEqual(readable_dirs, [])
        self.assertIn('a.txt', prompt)
        self.assertIn('do it', prompt)

    def test_it_may_read_the_files_of_its_focus(self):
        with mock.patch('dirdelta.ai._run_query', return_value={'summary': '', 'answer': 'It says hi', 'steps': []}) as query, \
                mock.patch('dirdelta.messages.show') as show:
            self.assertIsNone(self.sync._ask_ai(['a.txt', 'b.txt'], ['b.txt']))
        prompt, readable_dirs = query.call_args.args[:2]
        self.assertEqual(readable_dirs, [self.src_path])
        self.assertIn("read it at %s" % (os.path.join(self.src_path, 'b.txt'),), prompt)
        self.assertNotIn(os.path.join(self.src_path, 'a.txt'), prompt)
        self.assertEqual(show.call_args.args[:2], ('The AI says', ['It says hi']))

    def test_the_key_with_nothing_picked_asks_about_all_the_files(self):
        with mock.patch.object(Sync, '_ask_ai', return_value=None) as ask, helpers.scripted_files_picker(
                mock.Mock(side_effect=[picker.Picked('a', '', []), None])), \
                mock.patch('dirdelta.interactive_dir_sync.hashes_screen.jobs_of', return_value=[]):
            self.sync.browse()
        ask.assert_called_once_with(['a.txt', 'b.txt', 'c.txt'], [])

    def test_the_key_asks_about_the_picked_ones(self):
        with mock.patch.object(Sync, '_ask_ai', return_value=None) as ask, helpers.scripted_files_picker(
                mock.Mock(side_effect=[picker.Picked('a', '', ['b.txt']), None])), \
                mock.patch('dirdelta.interactive_dir_sync.hashes_screen.jobs_of', return_value=[]):
            self.sync.browse()
        ask.assert_called_once_with(['b.txt'], ['b.txt'])


class ActInDstTest(_TwoDirsTestCase):
    """Enter in the tree beside the picker, dst's"""

    def setUp(self):
        super().setUp()
        helpers.make_files(self.dst_path, ['repo/x.txt', 'repo/y.txt', 'meta/hashes.sqlite'])

    def enter(self, side_selected, confirmations=('Yes', 'Yes, remove them'), is_dry_run=False):
        """browse(), Enter in the side tree at side_selected, then choosing to remove it, confirming
        with confirmations"""
        answers = iter(confirmations)

        def pick_option(options, **kwargs):
            if options[-1].startswith('Remove'):
                self.options, self.shown = options, kwargs['shown_as']()
                return options[-1]
            return next(answers)
        picks = iter([picker.Picked(picker.SIDE_KEY, 'a.txt', [], side_selected), None])
        with helpers.scripted_files_picker(lambda relpaths: next(picks)) as pick_files, \
                mock.patch('dirdelta.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.interactive_dir_sync.hashes_screen.jobs_of', return_value=[]), \
                mock.patch('dirdelta.dryrun.DRYRUN', is_dry_run):
            self.sync.browse()
        return pick_files

    def test_enter_ends_picking_there(self):
        pick_files = self.enter('')
        self.assertTrue(pick_files.call_args.kwargs['side'].is_enter_picking)

    def test_a_dir_is_removed_and_the_replicas_diffed_anew(self):
        self.enter('repo')
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'repo', 'y.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'old', 'd.txt')))
        self.assertTrue(self.sync.has_changed)

    def test_src_lacks_nothing_more_after_removing_from_dst_of_what_it_has(self):
        helpers.make_files(self.src_path, ['repo/x.txt'])
        pick_files = self.enter('repo')
        # dst had src's repo/x.txt: now it's what dst lacks
        self.assertIn('repo/x.txt', pick_files.call_args.args[1])

    def test_it_says_where_it_removes_from_and_asks_twice(self):
        self.enter('repo', ('No',))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))
        self.assertFalse(self.sync.has_changed)

    def test_a_dry_run_changes_nothing(self):
        self.enter('repo', is_dry_run=True)
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))
        self.assertFalse(self.sync.has_changed)

    def test_d_there_goes_straight_to_confirming(self):
        with mock.patch('dirdelta.picker.pick_option', side_effect=['Yes', 'Yes, remove them']) as pick_option, \
                mock.patch('dirdelta.dryrun.DRYRUN', False):
            self.sync._act_in_dst('repo', True)
        self.assertTrue(helpers.labels_of(pick_option.call_args_list[0].args[0])[-1] == 'Yes')
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))

    def test_d_on_a_read_only_one_says_so(self):
        with mock.patch('dirdelta.interactive_dir_sync.is_writable', return_value=False), \
                mock.patch('dirdelta.picker.pick_option') as pick_option:
            self.assertIsNone(self.sync._act_in_dst('repo', True))
        pick_option.assert_not_called()
        self.assertEqual(interactive_dir_sync.messages.show.call_args.args[0], "Can't remove it")

    def test_the_picker_is_told_the_keys_there(self):
        pick_files = self.enter('')
        side = pick_files.call_args.kwargs['side']
        self.assertIn('d', side.keys)
        self.assertIn(':', side.keys)
        self.assertIn(('d', 'remove'), side.key_hints)
        self.assertTrue(pick_files.call_args.kwargs['enter_picks_selection'])
        self.assertEqual(pick_files.call_args.kwargs['none_picked_key_hints'], [('Enter', 'Pick & choose what to do')])

    def test_not_all_of_dst(self):
        self.enter('')
        self.assertEqual(interactive_dir_sync.messages.show.call_args.args[0], "That's all of %s" % (self.dst_path,))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))

    def test_a_read_only_one_cant(self):
        with mock.patch('dirdelta.interactive_dir_sync.is_writable', return_value=False):
            self.enter('repo', ('No',))
        self.assertIsInstance(self.shown[self.options[-1]], picker.Disabled)


class ExploreTest(_TwoDirsTestCase):
    """e and the menus' Explore, on a zip"""

    def setUp(self):
        super().setUp()
        self.zip_path = os.path.join(self.src_path, 'z.zip')
        with zipfile.ZipFile(self.zip_path, 'w') as archive:
            archive.writestr('in/side.txt', 'hello')

    def browse(self, picks):
        results = iter(picks + [None])
        with helpers.scripted_files_picker(lambda relpaths: next(results)), \
                mock.patch('dirdelta.interactive_dir_sync.hashes_screen.jobs_of', return_value=[]), \
                mock.patch('dirdelta.picker.view_files') as view:
            self.sync.browse()
        return view

    def test_the_key_shows_whats_in_it(self):
        view = self.browse([picker.Picked('e', 'z.zip', [])])
        self.assertEqual(view.call_args.args[:2], ('z.zip', ['in/side.txt']))

    def test_the_key_elsewhere_says_it_isnt_one(self):
        view = self.browse([picker.Picked('e', 'a.txt', [])])
        view.assert_not_called()
        self.assertEqual(interactive_dir_sync.messages.show.call_args.args[0], 'Not a zip')

    def test_the_menu_offers_it_on_a_zip_only(self):
        with mock.patch('dirdelta.picker.view_files') as view, helpers.answering_option_picker(['Explore']) as options:
            self.sync._act(['z.zip'])
        self.assertTrue(any(option.startswith('Explore') for option in helpers.labels_of(options.call_args.args[0])))
        self.assertEqual(view.call_args.args[1], ['in/side.txt'])
        with helpers.answering_option_picker([None]) as options:
            self.sync._act(['a.txt'])
        self.assertFalse(any(option.startswith('Explore') for option in helpers.labels_of(options.call_args.args[0])))


class ContextMenuTest(_TwoDirsTestCase):
    """: in the sync's picker"""

    def press(self, picks, answer):
        """browse(), ':' being pressed on the Picked of picks, then quitting; the menu answering answer
        (what its options start with). The options are self.options."""
        def pick_option(options, **kwargs):
            self.options = helpers.labels_of(options)
            self.shown = helpers.shown_of(options)
            return helpers.answer_of(options, answer)
        results = iter(picks + [None])
        with helpers.scripted_files_picker(lambda relpaths: next(results)) as pick_files, mock.patch('dirdelta.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.interactive_dir_sync.hashes_screen.jobs_of', return_value=[]):
            self.sync.browse()
        return pick_files

    def test_its_options_are_whats_there_with_their_keys(self):
        self.press([picker.Picked(':', 'a.txt', [])], 'Nothing')
        shown = [picker.unstyled(self.shown[option]) for option in self.options
                 if not isinstance(self.shown[option], picker.Skipped)]
        self.assertTrue(any(line.startswith('[Space]') and 'Pick a.txt' in line for line in shown))
        self.assertTrue(any(line.startswith('[a]') for line in shown))
        self.assertTrue(any(line.startswith('[Ctrl-X]') for line in shown))
        self.assertTrue(any(line.startswith('[cc]') for line in shown))
        self.assertTrue(any(line.startswith('[#]') for line in shown))
        # What only the picker does is shown, and can't be chosen
        self.assertTrue(any(isinstance(self.shown[option], picker.Skipped) and 'search' in self.shown[option].text
                            for option in self.options))

    def test_on_the_root_theres_nothing_to_open_or_rename(self):
        self.press([picker.Picked(':', '', [])], 'Nothing')
        self.assertFalse(any(option.startswith(('Open', 'Rename')) for option in self.options))

    def test_ask_ai_is_about_all_the_files(self):
        with mock.patch.object(Sync, '_ask_ai', return_value=None) as ask:
            self.press([picker.Picked(':', 'a.txt', [])], 'Ask AI')
        ask.assert_called_once_with(['a.txt', 'b.txt', 'c.txt'], ['a.txt'])

    def test_pick_comes_back_picked(self):
        pick_files = self.press([picker.Picked(':', 'b.txt', [])], 'Pick')
        self.assertEqual(pick_files.call_args.kwargs['picked'], ['b.txt'])

    def test_what_to_do_is_enters_menu_of_the_selected_one(self):
        with mock.patch.object(Sync, '_act', return_value=None) as act:
            self.press([picker.Picked(':', 'b.txt', [])], 'Choose what to do')
        act.assert_called_once_with(['b.txt'], 'b.txt')

    def test_open_opens_the_selected_one(self):
        with mock.patch('dirdelta.opening.Opener.press') as press:
            self.press([picker.Picked(':', 'b.txt', [])], 'Open')
        self.assertEqual(press.call_args.args[0], ['b.txt'])

    def test_with_files_picked_its_enters_menu(self):
        with mock.patch.object(Sync, '_act', return_value=None) as act, \
                mock.patch.object(Sync, '_context_menu') as menu:
            self.press([picker.Picked(':', 'a.txt', ['b.txt'])], 'Nothing')
        act.assert_called_once_with(['b.txt'], 'a.txt')
        menu.assert_not_called()


class FindMissingTest(unittest.TestCase):
    def test_what_dirdelta_keeps_in_a_replica_isnt_one_of_its_files(self):
        roots = [tempfile.mkdtemp(prefix='dirdelta-missing-') for _ in range(2)]
        for root in roots:
            self.addCleanup(shutil.rmtree, root)
        helpers.make_files(roots[0], ['a.txt', 'meta/hashes.sqlite', 'metal/b.txt'])
        a, b = [localdiskdirtree.LocalDiskDirTree(root, silent=True) for root in roots]
        self.assertEqual(interactive_dir_sync.find_missing(a, b).relpaths, ['a.txt', 'metal/b.txt'])

if __name__ == '__main__':
    unittest.main()
