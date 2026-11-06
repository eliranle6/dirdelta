"""The inbox and the sorted tree as replicas: read-only ones, two kinds of tree, logs, and run()"""
import json
import os
import shutil
import unittest
from unittest import mock

import helpers
from dirdelta import inbox
from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from dirdelta.known import log_entries
from dirdelta.known import replicas
from inbox_support import InboxSortTest, NOTHING, SURE, Sort, YES


class ReplicasTest(InboxSortTest):
    """Read-only replicas, trees of two kinds, logs and run()"""

    def test_live_changes_are_noted_for_the_logs(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='x'):
            self.sort([['a.txt'], ['b.jpg'], ['trip/c.jpg'], None],
                      ['Move it to a dir you pick', YES, 'Copy it to a dir you pick', YES, 'Remove it from', YES, SURE],
                      dirs=[os.path.join(self.root, 'docs')] * 2)
        changes = self.sorter.changes
        self.assertEqual(changes.summary(self.root), "added 1 file from %s; copied 1 file from %s" % (self.inbox, self.inbox))
        # An inbox has no log: none of it is noted for one
        self.assertEqual(changes.summary(self.inbox), "")
        self.assertEqual(changes.paths(), [self.root])
        # Not in a dry run
        self.sort([['b.jpg'], None], ['Remove it from', YES, SURE], is_dry_run=True)
        self.assertEqual(self.sorter.changes.paths(), [])

    def test_a_sort_reads_the_logs_and_offers_entries_once_done(self):
        with open(os.path.join(self.root, 'last_update.txt'), 'w') as log:
            log.write("17.05.2026 - removed old money.ods\n")
        known = replicas.Replicas()
        picks = [['a.txt'], None]
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)), \
                helpers.answering_option_picker(['Move it to a dir you pick', YES, 'Add it to its', log_entries.NO_ENTRY]) as pick, \
                mock.patch('dirdelta.ui.picker.pick_under_dir', return_value=('', os.path.join(self.root, 'docs'))), \
                mock.patch('dirdelta.ui.picker.view_files', return_value=True), \
                mock.patch('dirdelta.known.replicas.save'), mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.known.replicalog.identity', side_effect=lambda path: 'id:' + path), \
                mock.patch.object(Sort, 'prepare_hashing'), self.synchronously():
            inbox.run(self.inbox, self.root, known)
        # Seen at the start, and its log's last entry is the one added since
        self.assertIsNotNone(known.known['id:' + self.root]['seen'])
        self.assertEqual(known.known['id:' + self.root]['last_entry']['text'], "added 1 file from %s" % (self.inbox,))
        # An inbox has no log: it isn't a replica kept track of
        self.assertNotIn('id:' + self.inbox, known.known)
        self.assertFalse(self.exists('inbox', 'last_update.txt'))
        # Then offered for the changed one: the sorted tree (it's added the file), not the inbox the
        # file left
        headers = [call.kwargs['header'] for call in pick.call_args_list[2:]]
        self.assertIn("added 1 file from %s" % (self.inbox,), headers[0])
        self.assertFalse(any(self.inbox + '?' in header or 'moved 1 file' in header for header in headers))
        with open(os.path.join(self.root, 'last_update.txt')) as log:
            self.assertTrue(log.read().endswith(" - added 1 file from %s\n" % (self.inbox,)))

    def test_from_a_read_only_inbox_only_copying_is_left_and_its_said(self):
        self.read_only_inbox()
        self.sort([['a.txt'], None], [NOTHING])
        self.assertEqual(self.show.call_args_list[0].args[0], 'Read-only')
        self.assertIn('you can still copy', self.show.call_args_list[0].args[1][0])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertTrue(any(option.startswith('Copy it') for option in options))
        self.assertFalse(any(option.startswith(('Move', 'Remove')) for option in options))

    def test_into_a_read_only_sorted_tree_nothing_is_offered(self):
        self.read_only_root()
        self.sort([['a.txt'], None], [NOTHING])
        self.assertIn('no files can go into it', self.show.call_args_list[0].args[1][0])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertFalse(any(option.startswith('Copy') for option in options))
        self.assertEqual([option for option in options if option.startswith('Move')],
                         [option for option in options if 'in the inbox' in option or 'another dir in the inbox' in option])
        self.assertTrue(any(option.startswith('Remove') for option in options))

    def test_enter_in_the_side_tree_of_a_read_only_inbox_copies(self):
        self.read_only_inbox()
        sorter = Sort(self.inbox, self.root)
        with mock.patch.object(sorter, '_approve', return_value=None) as approve:
            sorter._move_to_side(['a.txt'], 'docs')
        self.assertEqual(approve.call_args.args[0], Sort.COPY_TO)

    def test_enter_in_a_read_only_side_tree_says_so(self):
        self.read_only_root()
        sorter = Sort(self.inbox, self.root)
        with mock.patch.object(sorter, '_approve') as approve:
            self.assertIsNone(sorter._move_to_side(['a.txt'], 'docs'))
        approve.assert_not_called()
        self.assertEqual(self.show.call_args.args[0], 'Read-only')

    def test_the_ais_plan_is_only_of_what_can_be_done(self):
        sorter = Sort(self.inbox, self.root)
        names = lambda: [action.name for action in sorter._ai_task(['a.txt']  , []).actions]
        self.assertEqual(len(names()), 4)
        with mock.patch('dirdelta.sync.replica_ops.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.inbox)):
            self.assertEqual(names(), [Sort.COPY_TO])
        with mock.patch('dirdelta.sync.replica_ops.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.root)):
            self.assertEqual(names(), [Sort.MOVE_IN_INBOX, Sort.REMOVE])

    def test_with_both_read_only_the_ai_isnt_asked(self):
        sorter = Sort(self.inbox, self.root)
        with mock.patch('dirdelta.sync.replica_ops.is_writable', return_value=False), \
                mock.patch('dirdelta.screens.aiplan_screen.ask') as ask:
            self.assertIsNone(sorter._ask_ai(['a.txt']))
        ask.assert_not_called()

    def test_a_copy_from_a_read_only_inbox_goes_through(self):
        self.read_only_inbox()
        self.sort([['a.txt'], None], ['Copy it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')], is_dry_run=False)
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_bad_pairs_are_refused(self):
        with self.assertRaises(inbox.InboxError):
            Sort(self.inbox, os.path.join(self.inbox, 'trip'))
        with self.assertRaises(inbox.InboxError):
            Sort(os.path.join(self.tmpdir, 'nope'), self.root)

    def test_a_move_between_two_trees_is_a_copy_then_a_removal(self):
        sorter = self.two_trees()
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            done = sorter._transfer([('trip/c.jpg', 'photos/trip/c.jpg'), ('a.txt', 'docs/a.txt')], True)
        self.assertEqual(sorted(done), [('a.txt', 'docs/a.txt'), ('trip/c.jpg', 'photos/trip/c.jpg')])
        with open(os.path.join(self.root, 'photos', 'trip', 'c.jpg')) as f:
            self.assertEqual(f.read(), 'trip/c.jpg')
        self.assertFalse(self.exists('inbox', 'trip'))
        self.assertTrue(os.path.isdir(self.inbox))

    def test_a_failed_copy_between_two_trees_keeps_the_inbox_file(self):
        sorter = self.two_trees()
        real_copy = shutil.copy2

        def copy(src, dst):
            if src.endswith('a.txt'):
                raise OSError('disk full')
            real_copy(src, dst)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=copy):
            done = sorter._transfer([('a.txt', 'docs/a.txt'), ('b.jpg', 'photos/b.jpg')], True)
        self.assertEqual(done, [('b.jpg', 'photos/b.jpg')])
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('inbox', 'b.jpg'))

    def test_a_copy_between_two_trees_keeps_the_inbox_files(self):
        sorter = self.two_trees()
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            sorter._transfer([('a.txt', 'docs/a.txt')], False)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))

    def test_a_local_inbox_and_a_drive_sorted_tree_get_a_tree_each(self):
        cache = os.path.join(self.tmpdir, 'files.txt')
        with open(cache, 'w') as f:
            f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            f.write(json.dumps({'id': 'me', 'name': 'me', 'parents': ['ROOT'],
                                'mimeType': 'application/vnd.google-apps.folder'}) + '\n')
        with mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', cache):
            sorter = Sort(self.inbox, 'cloud/me')
            with self.assertRaises(drivecache.DriveCacheError):
                Sort(self.inbox, 'cloud/nope')
        self.assertFalse(sorter.is_same_kind)
        self.assertIsInstance(sorter._root_tree, clouddirtree.CloudDirTree)
        self.assertEqual(sorter._inbox_tree.fullpath(), self.inbox)
        self.assertEqual(sorter.root_path, 'cloud/me')

    def test_run_records_the_sort(self):
        known = replicas.Replicas()
        with mock.patch('dirdelta.known.replicas.save') as save, \
                mock.patch.object(Sort, 'run'), mock.patch.object(Sort, 'prepare_hashing'):
            inbox.run(self.inbox, self.root, known)
        self.assertEqual(known.sorts, [(self.inbox, self.root)])
        save.assert_called_once_with(known)

    def test_run_offers_to_hash_the_local_ones_first(self):
        order = []
        with mock.patch('dirdelta.screens.hashes_screen.offer', side_effect=lambda jobs: order.append(
                    sorted(job.root for job in jobs)) or True), \
                mock.patch.object(Sort, 'run', side_effect=lambda: order.append('run')):
            inbox.run(self.inbox, self.root)
        self.assertEqual(order, [sorted([os.path.realpath(self.inbox), os.path.realpath(self.root)]), 'run'])

    def test_nothing_at_the_hashing_question_goes_back_without_sorting(self):
        with mock.patch('dirdelta.screens.hashes_screen.offer', return_value=False), \
                mock.patch.object(Sort, 'run') as run:
            inbox.run(self.inbox, self.root)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
