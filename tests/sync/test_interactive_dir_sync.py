"""A way of a sync: picking the missing files, and copying or removing them"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from dirdelta.known import log_entries
from dirdelta.sync import replica_ops
from dirdelta.trees import dirtree
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from dirdelta.ui import picker
from sync_way_support import NO, NOTHING, SURE, Sync, YES


class InteractiveDirSyncTest(unittest.TestCase):
    """src has a.txt, sub/b.txt and sub/c.txt, dst has only a.txt, so sub/b.txt and sub/c.txt are
    missing."""

    def setUp(self):
        self.src_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-sync-src-'))
        self.dst_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-sync-dst-'))
        helpers.make_files(self.src_root, ['a.txt', 'sub/b.txt', 'sub/c.txt'])
        helpers.make_files(self.dst_root, ['a.txt'])
        self.messages = []
        for patcher in (mock.patch('dirdelta.ui.messages.print_line',
                                   side_effect=lambda s, *a: self.messages.append(s)),
                        mock.patch('dirdelta.ui.messages.show')):
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
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
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
        changes = log_entries.Changes()
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], ['sub/c.txt'], None], ['Copy', YES, 'Remove', YES, SURE], changes=changes)
        self.assertEqual(changes.summary(self.dst_root), "copied 1 file from %s" % (self.src_root,))
        self.assertEqual(changes.summary(self.src_root), "removed 1 file")
        # Not in a dry run
        changes = log_entries.Changes()
        self._browse([['sub/b.txt'], None], ['Copy', YES], changes=changes)
        self.assertEqual(changes.paths(), [])

    def test_the_other_picks_stay_picked(self):
        # Both picked, but only one copied: the other's copy fails
        real_copy = localdiskdirtree.copying.shutil.copy2

        def copy(src, dst):
            if src.endswith('c.txt'):
                raise OSError('disk full')
            real_copy(src, dst)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=copy):
            self._browse([['sub/b.txt', 'sub/c.txt'], None], ['Copy', YES])
        self.assertEqual(self._offered()[1], (['sub/c.txt'], ['sub/c.txt']))

    def test_dry_run_copy_changes_nothing_and_drops_the_picks(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self._browse([['sub/b.txt', 'sub/c.txt'], None], ['Copy', YES])
        self.assertFalse(self.exists(self.dst_root, 'sub'))
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], []))
        self.assertFalse(self.sync.has_changed)
        self.assertIn('Dry run, not copying sub/b.txt (1 out of 2)', self.messages)

    def test_remove_is_confirmed_twice_then_removes(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
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
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt'], None], ['Remove', YES, NO])
        self.assertTrue(self.exists(self.src_root, 'sub/b.txt'))
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt']))
        self.assertFalse(self.sync.has_changed)

    def test_dry_run_remove_leaves_disk_untouched(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self._browse([['sub/b.txt'], None], ['Remove', YES, SURE])
        self.assertTrue(self.exists(self.src_root, 'sub/b.txt'))
        self.assertIn('Dry run, not removing sub/b.txt (1 out of 1)', self.messages)

    def test_the_action_menu_starts_with_nothing_which_goes_back_to_the_picks(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._browse([picker.Picked('', 'sub/c.txt', ['sub/b.txt']), None], [NOTHING])
        options = [picker.option_label(option) for option in self.pick_option.call_args_list[0].args[0]]
        self.assertEqual(options[0], NOTHING)
        # Each kind apart, after a blank line
        self.assertEqual([option.split(' ')[0] for option in options[1:]],
                         ['', 'Ask', '', 'Copy', '', 'Remove', '', 'Rename', 'Rename', '', 'Open'])
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt']))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'sub/c.txt')

    def test_ctrl_x_opens_the_selected_file(self):
        with mock.patch('dirdelta.ui.opening.Opener.open_in_background') as open_in_background:
            self._browse([None], [])
            kwargs = self.pick_files.call_args.kwargs
            self.assertEqual(kwargs['notify_keys'], '\x18')
            self.assertIn("  %-17s%s" % ('Ctrl-X', 'open'), kwargs['help_lines'])
            kwargs['on_notify']('\x18', 'sub/c.txt', [])
            kwargs['on_notify']('\x18', 'sub/c.txt', ['sub/b.txt', 'sub/c.txt'])
        files = {'sub/b.txt', 'sub/c.txt'}
        # Not the picked ones: the menu's Open opens them
        self.assertEqual(open_in_background.call_args_list, [mock.call(['sub/c.txt'], files)] * 2)

    def test_open_in_the_menu_opens_the_picked_files_and_goes_back_to_them(self):
        with mock.patch('dirdelta.ui.opening.Opener.open_in_background') as open_in_background:
            self._browse([picker.Picked('', 'sub', ['sub/b.txt', 'sub/c.txt']), None],
                         ['Open the 2 files with their programs'])
        open_in_background.assert_called_once_with(['sub/b.txt', 'sub/c.txt'], ['sub/b.txt', 'sub/c.txt'])
        self.assertEqual(self._offered()[1], (['sub/b.txt', 'sub/c.txt'], ['sub/b.txt', 'sub/c.txt']))

    def test_quitting_the_menu_or_a_confirmation_is_nothing(self):
        for answers in ([None], ['Copy', None], ['Copy', NO]):
            with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
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
        with mock.patch('dirdelta.sync.replica_ops.os.access',
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
        with mock.patch('dirdelta.ui.messages.ask', return_value='a.txt'), mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            # sub/b.txt renamed to a.txt there: still missing (dst has a.txt, not sub/a.txt)
            self._browse([picker.Picked('cc', 'sub/b.txt', ['sub/b.txt']), None], [])
        self.assertTrue(self.exists(self.src_root, 'sub/a.txt'))
        kwargs = self.pick_files.call_args.kwargs
        self.assertEqual(self.pick_files.call_args.args[1], ['sub/a.txt', 'sub/c.txt'])
        self.assertEqual(kwargs['selected'], 'sub/a.txt')
        self.assertEqual(kwargs['picked'], ['sub/a.txt'])

    def test_two_cloud_replicas_cant_copy(self):
        src = clouddirtree.CloudDirTree('cloud/a')
        src.add_file_by_relpath('x')
        self._browse([['x'], None], [NOTHING], src, clouddirtree.CloudDirTree('cloud/b'))
        self.assertIn("Copy the 1 file to cloud/b: can't: both are Google Drive's", self.disabled())

    def test_nothing_missing_says_so_without_a_picker(self):
        helpers.make_files(self.dst_root, ['sub/b.txt', 'sub/c.txt'])
        self._browse([], [])
        title, lines, _ = messages.show.call_args.args
        self.assertEqual(title, 'Nothing to do')
        self.assertEqual(lines, ["%s has all of %s's files." % (self.dst_root, self.src_root)])

    def test_after_the_last_ones_are_done_it_says_so_and_ends(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._browse([['sub/b.txt', 'sub/c.txt']], ['Copy', YES])
        self.assertEqual(messages.show.call_args.args[0], 'Nothing to do')

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

    def test_a_cloud_replica_is_named_as_a_cloud_path(self):
        # Not by its path in Drive (/mein), which reads like a local dir
        src = clouddirtree.CloudDirTree('cloud/mein')
        src.add_file_by_relpath('song.mp3')
        with mock.patch('dirdelta.drive.drivecache.user', return_value='me'):
            self._browse([['song.mp3'], None], ['Remove', NO], src, dirtree.DirTree('/local'))
        self.assertEqual(self.pick_files.call_args.args[0], 'Cloud(me):/mein')
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        self.assertEqual(header[0], 'Remove 1 file from cloud/mein?')


class FindMissingTest(unittest.TestCase):
    def test_what_dirdelta_keeps_in_a_replica_isnt_one_of_its_files(self):
        roots = [tempfile.mkdtemp(prefix='dirdelta-missing-') for _ in range(2)]
        for root in roots:
            self.addCleanup(shutil.rmtree, root)
        helpers.make_files(roots[0], ['a.txt', 'meta/hashes.sqlite', 'metal/b.txt'])
        a, b = [localdiskdirtree.LocalDiskDirTree(root, silent=True) for root in roots]
        self.assertEqual(replica_ops.find_missing(a, b).relpaths, ['a.txt', 'metal/b.txt'])


if __name__ == '__main__':
    unittest.main()
