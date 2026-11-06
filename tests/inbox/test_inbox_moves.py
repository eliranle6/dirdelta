"""Moving and copying the inbox's files: to a dir picked, a new one, a typed name; the approval"""
import os
import unittest
from unittest import mock

import helpers
from dirdelta.known import replicas
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.ui import renaming
from inbox_support import InboxSortTest, NO, NOTHING, Sort, YES


class MovesTest(InboxSortTest):
    """Moves and copies"""

    def test_a_move_stopped_with_ctrl_c_says_what_was_left(self):
        # Stopped while transferring, before it said what it did: what's there now is what was done
        def stopped(*_, **__):
            raise KeyboardInterrupt()
        with mock.patch.object(Sort, '_transfer', side_effect=stopped), \
                mock.patch('dirdelta.trees.localdiskdirtree.LocalReplica.move_files', side_effect=stopped):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')],
                      is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertEqual(self.show.call_args.args[0], 'Not all were moved')

    def test_o_makes_a_new_dir_beside_the_selected_one(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='letters'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[('o', os.path.join(self.root, 'docs'))], is_dry_run=False)
        # In docs/'s dir, the root, not in docs/
        self.assertTrue(self.exists('sorted', 'letters', 'a.txt'))
        keys = self.pick_under_dir.call_args.kwargs['keys']
        self.assertIn('o', keys)
        self.assertIn('O', keys)

    def test_files_are_moved_to_another_dir_of_the_inbox(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='lists'):
            self.sort([['a.txt'], None], ['Move it to another dir in the inbox', YES],
                      dirs=[('n', self.inbox)], is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'lists', 'a.txt'))
        self.assertFalse(self.exists('inbox', 'a.txt'))
        # Picked from the inbox's dirs
        self.assertEqual(self.pick_under_dir.call_args.args[0], self.inbox)

    def test_move_to_a_picked_dir(self):
        self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')])
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))
        self.assertFalse(self.exists('inbox', 'a.txt'))
        # The dir picker: the sorted tree's dirs, read as shown
        args, kwargs = self.pick_under_dir.call_args
        self.assertEqual(args, (self.root,))
        self.assertTrue(kwargs['dirs_only'] and kwargs['lazy'])
        # Back to the files left
        self.assertEqual(self.pick_files.call_args.args[1], ['b.jpg', 'trip/c.jpg'])

    def test_a_move_waits_for_enter_and_says_if_some_werent_moved(self):
        with mock.patch('dirdelta.ui.messages.progress_screen', wraps=messages.progress_screen) as screen:
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')])
        # "Press Enter to continue" once it's done
        self.assertNotIn('wait', screen.call_args.kwargs)
        self.show.assert_not_called()
        # One that's there already is skipped: not moved
        helpers.make_files(self.root, ['docs/b.jpg'])
        self.sort([['b.jpg', 'trip/c.jpg'], None], ['Move the 2 files to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')])
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Not all were moved')
        self.assertEqual(lines[1:], ['  b.jpg'])
        self.assertTrue(self.exists('sorted', 'docs', 'c.jpg'))

    def test_the_approval_shows_the_tree_it_makes(self):
        self.sort([['a.txt', 'trip/c.jpg'], None], ['Move the 2 files to a dir you pick', YES],
                  dirs=[os.path.join(self.root, 'new')])
        root, targets = self.view_files.call_args.args
        self.assertEqual((root, targets), (self.root, ['new/a.txt', 'new/c.jpg']))
        previews = self.view_files.call_args.kwargs['previews']
        self.assertEqual(previews['new/c.jpg'][0], 'From: %s/trip/c.jpg' % (self.inbox,))
        self.assertIn('In a new dir.', previews['new/a.txt'])
        self.assertIn('into 1 dirs of %s (1 of them new)' % (self.root,), self.view_files.call_args.kwargs['header'])
        confirm = self.pick_option.call_args_list[1]
        self.assertEqual(confirm.args[0], [NO, YES])
        self.assertTrue(self.exists('sorted', 'new', 'c.jpg'))
        # The inbox's emptied subdir goes, the inbox stays
        self.assertFalse(self.exists('inbox', 'trip'))

    def test_quitting_the_approval_moves_nothing(self):
        self.sort([['a.txt'], None], ['Move it to a dir you pick'], dirs=[os.path.join(self.root, 'docs')],
                  view=False)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['a.txt'])

    def test_files_of_the_same_name_to_one_dir_are_refused(self):
        helpers.make_files(self.inbox, ['other/a.txt'])
        self.sort([['a.txt', 'other/a.txt'], None], ['Move the 2 files to a dir you pick'], dirs=[self.root])
        self.assertEqual(self.show.call_args.args[0], 'Files of the same name')
        self.view_files.assert_not_called()

    def test_the_inbox_is_kept_when_emptied(self):
        self.sort([['a.txt', 'b.jpg', 'trip/c.jpg']], ['Move the 3 files to a dir you pick', YES], dirs=[self.root])
        self.assertTrue(os.path.isdir(self.inbox))
        self.assertEqual(os.listdir(self.inbox), [])
        self.assertEqual(self.show.call_args.args[0], 'The inbox is empty')

    def test_copy_keeps_the_inbox_file(self):
        self.sort([['b.jpg'], None], ['Copy it to a dir you pick', YES], dirs=[os.path.join(self.root, 'photos')])
        self.assertTrue(self.exists('sorted', 'photos', 'b.jpg'))
        self.assertTrue(self.exists('inbox', 'b.jpg'))
        # Done, so no longer picked
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], [])

    def test_a_dry_run_changes_nothing(self):
        self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[self.root], is_dry_run=True)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('sorted', 'a.txt'))

    def test_a_file_cant_be_moved_into_dirdeltas_own_dir(self):
        for picked in (os.path.join(self.root, 'meta'), os.path.join(self.root, 'meta', 'sub')):
            self.show.reset_mock()
            self.sort([['a.txt'], None], ['Move it to a dir you pick'], dirs=[picked], is_dry_run=False)
            self.assertEqual(self.show.call_args.args[0], "That's dirdelta's")
            self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('sorted', 'meta', 'a.txt'))

    def test_a_new_dir_in_dirdeltas_own_is_refused_too(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='meta/new'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick'], dirs=[('o', os.path.join(self.root, 'docs'))],
                      is_dry_run=False)
        self.assertEqual(self.show.call_args.args[0], "That's dirdelta's")
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_the_dir_picker_leaves_out_what_cant_be_picked(self):
        self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')])
        self.assertEqual(self.pick_under_dir.call_args.kwargs['excluded'], ['meta'])

    def test_it_leaves_out_an_inbox_in_the_sorted_tree_too(self):
        os.makedirs(os.path.join(self.root, 'in'), exist_ok=True)
        sorter = Sort(os.path.join(self.root, 'in'), self.root)
        with helpers.scripted_dir_picker(None) as pick:
            sorter._pick_dir('move', '1 file')
            self.assertEqual(pick.call_args.kwargs['excluded'], ['meta', 'in'])
            # Moving in the inbox, it's what's picked in
            sorter._pick_dir('move', '1 file', in_inbox=True)
            self.assertEqual(pick.call_args.kwargs['excluded'], ['meta'])

    def test_cc_renames_the_selected_file_what_claude_said_going_with_it(self):
        self.sorter = None
        with mock.patch('dirdelta.ui.messages.ask', return_value='list.txt'), mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            sorter = Sort(self.inbox, self.root)
            sorter._claude.descriptions['a.txt'] = 'a list'
            moved = sorter._rename_selected('a.txt')
        self.assertEqual(moved, {'a.txt': 'list.txt'})
        self.assertTrue(self.exists('inbox', 'list.txt'))
        self.assertEqual(sorter._claude.descriptions, {'list.txt': 'a list'})

    def test_cc_in_the_picker_shows_it_again_on_the_renamed_one(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='beach'):
            self.sort([picker.Picked(renaming.PRESSED, 'trip', []), None], [], is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'beach', 'c.jpg'))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'beach')
        self.assertEqual(self.pick_files.call_args.kwargs['twice_keys'], 'c')

    def test_cc_in_the_dir_picker_renames_a_sorted_dir_then_picks_again(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='documents'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[(renaming.PRESSED, os.path.join(self.root, 'docs')), os.path.join(self.root, 'documents')])
        self.assertTrue(self.exists('sorted', 'documents', 'old.txt'))
        self.assertTrue(self.exists('sorted', 'documents', 'a.txt'))

    def test_a_typed_name_in_a_picked_dir(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='list.txt') as ask:
            self.sort([['a.txt'], None], ['Move it to a dir you pick, under a name you type', YES], dirs=[os.path.join(self.root, 'docs')])
        # Without Claude's, its own
        self.assertEqual(ask.call_args.args[3], 'a.txt')
        self.assertTrue(self.exists('sorted', 'docs', 'list.txt'))

    def test_a_typed_name_isnt_a_path_and_is_for_one_file(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='../x.txt'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick, under a name you type'], dirs=[os.path.join(self.root, 'docs')])
        self.assertEqual(self.show.call_args.args[0], 'Not a name')
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.sort([['a.txt', 'b.jpg'], None], [NOTHING])
        # A name is typed for one file: not offered for two
        self.assertFalse(any("a name you type" in option for option in helpers.labels_of(self.pick_option.call_args.args[0])))

    def test_a_new_dir_is_made_in_the_selected_one(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='2026/taxes/') as ask:
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[('n', os.path.join(self.root, 'docs'))])
        self.assertIn('n', self.pick_under_dir.call_args.kwargs['keys'])
        self.assertEqual(ask.call_args.args[0], "A new dir in %s/docs/" % (self.root,))
        self.assertTrue(self.exists('sorted', 'docs', '2026', 'taxes', 'a.txt'))

    def test_a_new_dirs_name_isnt_a_path_out(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='../x'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick'], dirs=[('n', self.root)])
        self.assertEqual(self.show.call_args.args[0], "Not a dir's name")
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_the_dirs_moved_to_are_offered_first_next_time(self):
        known = replicas.Replicas()
        with mock.patch('dirdelta.known.replicas.save') as save:
            # The first time, there are none: straight to the dir picker
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')],
                      known=known)
            self.assertEqual(known.dirs_of(self.root), ['docs'])
            save.assert_called_with(known)
            # Then the recent ones, after picking one (first), a blank line apart
            self.sort([['b.jpg'], None], ['Copy it to a dir you pick', 'Recent: docs/', YES], known=known)
            menu = self.pick_option.call_args_list[1]
            self.assertEqual(menu.args[0], [Sort.PICK_DIR, picker.BLANK, 'Recent: docs/'])
            self.assertIn(self.root, menu.kwargs['header'])
            self.assertTrue(self.exists('sorted', 'docs', 'b.jpg'))
            # A new one, or one picked, goes to the top; one not moved to (No) doesn't
            with mock.patch('dirdelta.ui.messages.ask', return_value='new'):
                self.sort([['trip/c.jpg'], None], ['Move it to a dir you pick', 'Pick a dir', YES],
                          dirs=[('n', os.path.join(self.root, 'photos'))], known=known)
                self.sort([['b.jpg'], None], ['Move it to a dir you pick', 'Pick a dir', NO],
                          dirs=[os.path.join(self.root, 'photos')], known=known)
        self.assertEqual(known.dirs_of(self.root), ['photos/new', 'docs'])

    def test_a_dir_in_the_inbox_cant_be_the_destination(self):
        root_with_inbox = self.tmpdir
        sorter = Sort(self.inbox, root_with_inbox)
        with mock.patch('dirdelta.ui.picker.pick_under_dir', return_value=('', os.path.join(self.inbox, 'trip'))):
            self.assertIsNone(sorter._pick_dir('move', '1 file'))
        self.assertEqual(self.show.call_args.args[0], "That's the inbox")


if __name__ == '__main__':
    unittest.main()
