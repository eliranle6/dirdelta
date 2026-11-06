"""What Claude says of the inbox's files: descriptions, where they go, and moving them there"""
import os
import unittest
from unittest import mock

import helpers
from dirdelta.claude import ai
from dirdelta.inbox import constants
from dirdelta.ui import picker
from inbox_support import InboxSortTest, NOTHING, Sort, YES


class ClaudeTest(InboxSortTest):
    """Claude's descriptions and recommendations"""

    def test_a_file_gone_during_a_batch_is_left_out_and_not_called_failed(self):
        sorter = self.drive_inbox()
        with mock.patch.object(sorter, '_downloaded', return_value='/tmp/x'), \
                mock.patch('dirdelta.claude.ai.describe', return_value={'a.txt': 'a note'}):
            sorter._describe(['a.txt', 'gone.txt'])
        self.assertEqual(sorter._descriptions, {'a.txt': 'a note'})
        self.assertEqual(sorter._failed, {})

    def test_claudes_dir_under_the_files_own_name_isnt_offered_when_its_claudes_name(self):
        with self.claude_places():
            self.sort([['a.txt'], ['a.txt'], None], ['Ask Claude', NOTHING])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertIn("Move it to Claude's recommendation: %s/docs/a.txt" % (self.root,), options)
        self.assertFalse(any(option.startswith("Move it to Claude's dir, keeping") for option in options))
        self.assertFalse(any("under Claude's name" in option for option in options))

    def test_descriptions_are_shown_after_the_names(self):
        with self.ask_claude({'a.txt': {'description': 'a shopping list'}}):
            # Described in the background; quitting waits for it
            self.sort([['a.txt'], None], ['Describe it'])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(labels, {'a.txt': picker.styled([('a.txt', None), ('  ', None),
                                                          ('[claude: a shopping list]', constants.CLAUDE_STYLE)]), '': ''})
        self.assertEqual(self.queries[0][:2], (['description'], ai.MODEL))
        # Kept: shown on the next run too, without asking
        with mock.patch('dirdelta.claude.ai.query.run_query', side_effect=AssertionError('asked again')):
            self.sort([None], [])
        self.assertEqual(self.pick_files.call_args.kwargs['shown_as'](), labels)

    def test_ctrl_i_describes_the_picked_files_or_the_selected_ones_in_the_background(self):
        with self.ask_claude({'a.txt': {'description': 'a list'}, 'b.jpg': {'description': 'a cat'},
                              'trip/c.jpg': {'description': 'a beach'}}):
            self.sort([None], [])
            kwargs = self.pick_files.call_args.kwargs
            self.assertEqual(kwargs['notify_keys'], '\t\x18')
            self.assertTrue(kwargs['enter_picks_selection'])
            kwargs['on_notify']('\t', 'trip', [])
            self.sorter.wait_for_claude()
            self.assertEqual(self.sorter._descriptions, {'trip/c.jpg': 'a beach'})
            kwargs['on_notify']('\t', 'trip/c.jpg', ['a.txt'])
            self.sorter.wait_for_claude()
        self.assertEqual(sorted(self.sorter._descriptions), ['a.txt', 'trip/c.jpg'])

    def test_ctrl_i_asks_anew_about_files_claude_described_and_placed_before(self):
        answers = {'a.txt': {'description': 'a list', 'action': 'move', 'path': 'docs/a.txt', 'reason': 'a doc'}}
        with self.ask_claude(answers):
            self.sort([None], [])
            on_notify = self.pick_files.call_args.kwargs['on_notify']
            on_notify('\t', 'a.txt', [])
            self.sorter.wait_for_claude()
            self.assertEqual(len(self.queries), 2)
            # It changed since: asked again, not from the cache
            answers['a.txt'] = {'description': 'a shopping list', 'action': 'move', 'path': 'lists/a.txt',
                                'reason': 'a list'}
            on_notify('\t', 'a.txt', [])
            self.sorter.wait_for_claude()
        self.assertEqual(len(self.queries), 4)
        self.assertEqual(self.sorter._descriptions['a.txt'], 'a shopping list')
        self.assertEqual(self.sorter._target('a.txt'), 'lists/a.txt')
        self.assertEqual(self.sorter._anew, set())
        # And kept so next time
        self.assertEqual(ai.describe([ai.File('a.txt', None, self.sorter._size('a.txt'))], self.sorter._cache_key),
                         {'a.txt': 'a shopping list'})

    def test_the_menus_ask_claude_where_asks_anew_too(self):
        with self.ask_claude({'a.txt': {'description': 'a list', 'action': 'move', 'path': 'docs/a.txt',
                                        'reason': 'a doc'}}):
            self.sort([['a.txt'], ['a.txt'], None], ['Ask Claude', 'Ask Claude where it goes', NOTHING])
        self.assertIn("Ask Claude where it goes in %s, while you go on (anew: asked before)" % (self.root,),
                      helpers.labels_of(self.pick_option.call_args_list[1].args[0]))
        self.assertEqual(len(self.queries), 4)

    def test_recommendations_are_shown_and_moved_to(self):
        with self.ask_claude({'b.jpg': {'description': 'a cat', 'action': 'move', 'path': 'photos/cats/b.jpg',
                                        'reason': 'a cat photo'},
                              'trip/c.jpg': {'description': 'a beach', 'action': 'move',
                                             'path': 'photos/trips/2024/beach.jpg', 'reason': 'a trip photo'}}):
            self.sort([['b.jpg', 'trip/c.jpg'], ['b.jpg'], ['b.jpg', 'trip/c.jpg'], None],
                      ['Ask Claude', NOTHING, "Move the 2 files to Claude's recommendations (2 dirs, 1 renamed)", YES])
        # Described first (reading them), then placed by the descriptions
        self.assertEqual([query[:2] for query in self.queries],
                         [(['description'], ai.MODEL), (['action', 'path', 'reason'], ai.MODEL)])
        self.assertIn("b.jpg (size 5 bytes): a cat", self.queries[1][2])
        menus = [helpers.labels_of(call.args[0]) for call in self.pick_option.call_args_list]
        # One destination: the menu names it
        self.assertIn("Move it to Claude's recommendation: %s/photos/cats/b.jpg" % (self.root,), menus[1])
        self.assertTrue(self.exists('sorted', 'photos', 'cats', 'b.jpg'))
        # Renamed, as Claude recommended
        self.assertTrue(self.exists('sorted', 'photos', 'trips', '2024', 'beach.jpg'))
        view = self.view_files.call_args.kwargs['previews']['photos/trips/2024/beach.jpg']
        self.assertIn("Renamed, from:", view)
        # What Claude said of it went with it
        moved = ai.File('beach.jpg', None, 10)
        self.assertEqual(ai.cached([moved], lambda file: '%s/photos/trips/2024/beach.jpg\t10' % (self.root,),
                                   self.root)[0], {'beach.jpg': 'a beach'})
        self.assertIn("  photos/cats/", self.sent_previews(self.pick_files.call_args_list[1])['b.jpg'])

    def test_moved_to_claudes_dirs_keeping_their_names(self):
        with self.claude_places():
            self.sort([['b.jpg', 'trip/c.jpg'], ['b.jpg', 'trip/c.jpg'], None],
                      ['Ask Claude', "Move the 2 files to Claude's dir, keeping", YES])
        self.assertTrue(self.exists('sorted', 'photos', 'cats', 'b.jpg'))
        self.assertTrue(self.exists('sorted', 'photos', 'trips', '2024', 'c.jpg'))

    def test_moved_to_a_picked_dir_under_claudes_names(self):
        with self.claude_places():
            self.sort([['a.txt', 'trip/c.jpg'], ['a.txt', 'trip/c.jpg'], None],
                      ['Ask Claude', "Move the 2 files to a dir you pick, under Claude's names", YES], dirs=[os.path.join(self.root, 'photos')])
        # The one Claude didn't rename keeps its name
        self.assertTrue(self.exists('sorted', 'photos', 'a.txt'))
        self.assertTrue(self.exists('sorted', 'photos', 'beach.jpg'))

    def test_a_typed_name_starts_as_claudes(self):
        with self.claude_places(), mock.patch('dirdelta.ui.messages.ask', return_value='sunset.jpg') as ask:
            self.sort([['trip/c.jpg'], ['trip/c.jpg'], None],
                      ['Ask Claude', "Move it to Claude's dir, under a name you type", YES])
        self.assertEqual(ask.call_args.args[3], 'beach.jpg')
        self.assertIn('[claude: a beach]', ask.call_args.args[1])
        self.assertTrue(self.exists('sorted', 'photos', 'trips', '2024', 'sunset.jpg'))
        self.assertFalse(self.exists('inbox', 'trip', 'c.jpg'))

    def test_the_previews_are_sent_again_as_they_change(self):
        sorter = Sort(self.inbox, self.root)
        sends = []

        def send(found=None, default=None):
            sends.append(dict(found))
            if len(sends) == 1:
                sorter._descriptions['a.txt'] = 'a list'
            elif len(sends) == 3:
                raise picker.PickerClosed()
        with mock.patch('dirdelta.inbox.previews.PREVIEWS_INTERVAL', 0), self.assertRaises(picker.PickerClosed):
            sorter._send_previews(['a.txt', 'b.jpg'], send)
        self.assertEqual(sorted(sends[0]), ['a.txt', 'b.jpg'])
        # Only the one that changed
        self.assertEqual(list(sends[1]), ['a.txt'])
        self.assertIn("  a list", sends[1]['a.txt'])
        self.assertEqual(sends[2], {})

    def test_claudes_errors_are_said(self):
        with mock.patch('dirdelta.claude.ai.query.run_query', side_effect=ai.AIError('not logged in')):
            self.sort([['a.txt'], None], ['Describe it'])
            self.assertEqual(self.sorter._failed, {'a.txt': 'not logged in'})
            self.assertEqual(self.sorter._shown_as(['a.txt'])[''], "Claude: couldn't do 1 file")
            self.assertIn("  not logged in", self.sorter._previews(['a.txt'])['a.txt'])

    def test_ctrl_i_also_says_where_they_go(self):
        with self.ask_claude({'b.jpg': {'description': 'a cat', 'action': 'move', 'path': 'photos/cats/b.jpg',
                                        'reason': 'a cat photo'}}):
            self.sort([None], [])
            self.pick_files.call_args.kwargs['on_notify']('\t', 'b.jpg', [])
            self.sorter.wait_for_claude()
        self.assertEqual(self.sorter._target('b.jpg'), 'photos/cats/b.jpg')
        self.assertEqual([query[0] for query in self.queries], [['description'], ['action', 'path', 'reason']])

    def test_the_sorted_trees_dirs_for_claude_leave_the_inbox_out(self):
        os.makedirs(os.path.join(self.root, 'unsorted', 'deep'))
        sorter = Sort(os.path.join(self.root, 'unsorted'), self.root)
        self.assertEqual(sorter._root_dirs(), {'': [], 'docs': ['old.txt'], 'photos': ['old.jpg']})


if __name__ == '__main__':
    unittest.main()
