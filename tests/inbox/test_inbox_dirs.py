"""An inbox's dir as a whole: what Claude says of it, and moving or removing it whole"""
import os
import unittest
from unittest import mock

import helpers
from dirdelta.inbox import constants
from dirdelta.inbox import formatting
from dirdelta.ui import picker
from inbox_support import InboxSortTest, NOTHING, SURE, Sort, YES


class DirsTest(InboxSortTest):
    """Dirs as wholes"""

    def test_ctrl_i_on_a_dir_asks_about_it_as_a_whole(self):
        helpers.make_files(self.inbox, ['trip/d.jpg', 'trip/day2/e.jpg'])
        sorter = Sort(self.inbox, self.root)
        files = sorter._inbox_files()
        answer = {'action': 'move', 'path': '/photos/2024/rome trip/', 'summary': 'Rome trip photos.',
                  'reason': 'one trip'}
        with self.claude_on_dirs(answer) as query:
            sorter._on_key(constants.DESCRIBE_KEY, 'trip', [], files)
            sorter.wait_for_claude()
        self.assertEqual(sorter._claude.dir_recommendation('trip'),
                         {'action': 'move', 'path': 'photos/2024/rome trip', 'summary': 'Rome trip photos',
                          'reason': 'one trip'})
        # Its files described first (all three: no more than DIR_FILES_DESCRIBED), not asked where each goes
        self.assertEqual(sorter._claude.descriptions, {relpath: 'a beach at sunset' for relpath in
                                                ['trip/c.jpg', 'trip/d.jpg', 'trip/day2/e.jpg']})
        self.assertEqual(sorter._claude.recommendations, {})
        prompt = query.call_args.args[0]
        self.assertIn("Its name: trip", prompt)
        self.assertIn("3 files", prompt)
        self.assertIn("3 .jpg", prompt)
        self.assertIn("What day2/e.jpg is: a beach at sunset", prompt)
        self.assertIn("photos (e.g. old.jpg)", prompt)
        # Shown after its name, and beside it
        sorter._inbox_files()
        labels = sorter._shown_as(files)
        self.assertEqual(picker.unstyled(labels['trip']), 'trip  [claude: Rome trip photos]')
        preview = '\n'.join(picker.unstyled(line) for line in sorter._previews(files)['trip'])
        self.assertIn("Move it to:", preview)
        self.assertIn("photos/2024/rome trip/", preview)
        self.assertIn("one trip", preview)
        # Kept: a sort of the same inbox has it
        again = Sort(self.inbox, self.root)
        again._load_cached(again._inbox_files())
        self.assertEqual(again._claude.dir_recommendation('trip')['path'], 'photos/2024/rome trip')
        # Picked files, or the root: each file, as before
        with mock.patch.object(Sort, 'ask_in_background') as ask:
            sorter._on_key(constants.DESCRIBE_KEY, 'trip', ['trip/c.jpg'], files)
            sorter._on_key(constants.DESCRIBE_KEY, '', [], files)
        self.assertEqual([call.args[0] for call in ask.call_args_list], [['trip/c.jpg'], files])

    def test_a_dir_that_changed_is_asked_about_anew(self):
        self.cache_dir_recommendation('trip', {'action': 'split', 'path': '', 'summary': 'mixed', 'reason': 'r'})
        sorter = Sort(self.inbox, self.root)
        sorter._load_cached(sorter._inbox_files())
        self.assertEqual(sorter._claude.dir_recommendation('trip')['action'], 'split')
        preview = '\n'.join(picker.unstyled(line) for line in sorter._previews(sorter._inbox_files())['trip'])
        self.assertIn("Its files don't go together", preview)
        helpers.make_files(self.inbox, ['trip/new.jpg'])
        sorter._load_cached(sorter._inbox_files())
        self.assertIsNone(sorter._claude.dir_recommendation('trip'))
        preview = '\n'.join(picker.unstyled(line) for line in sorter._previews(sorter._inbox_files())['trip'])
        self.assertIn("Ctrl-I asks Claude about the dir", preview)

    def test_claude_failing_on_a_dir_says_so(self):
        sorter = Sort(self.inbox, self.root)
        files = sorter._inbox_files()
        with self.claude_on_dirs({'action': 'move', 'path': '..', 'summary': 's', 'reason': 'r'}):
            sorter._on_key(constants.DESCRIBE_KEY, 'trip', [], files)
            sorter.wait_for_claude()
        self.assertIsNone(sorter._claude.dir_recommendation('trip'))
        preview = '\n'.join(picker.unstyled(line) for line in sorter._previews(files)['trip'])
        self.assertIn("failed", preview)

    def test_the_dir_moves_whole_to_claudes_recommendation(self):
        helpers.make_files(self.inbox, ['trip/day2/e.jpg'])
        self.cache_dir_recommendation('trip', {'action': 'move', 'path': 'photos/rome', 'summary': 'Rome',
                                               'reason': 'one trip'})
        self.sort([picker.Picked('', 'trip', ['trip/c.jpg', 'trip/day2/e.jpg']), None],
                  ["Move the dir trip/ (2 files) to Claude's recommendation", YES])
        self.assertTrue(self.exists('sorted', 'photos', 'rome', 'c.jpg'))
        self.assertTrue(self.exists('sorted', 'photos', 'rome', 'day2', 'e.jpg'))
        self.assertFalse(self.exists('inbox', 'trip'))
        menu = helpers.labels_of(self.pick_option.call_args_list[0].args[0])
        self.assertIn("Move the dir trip/ (2 files) to Claude's recommendation: %s/photos/rome/" % (self.root,), menu)
        # Not offered for some of its files
        self.sort([picker.Picked('', 'trip', ['a.txt']), None], [NOTHING])
        menu = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertFalse([label for label in menu if 'the dir' in label])

    def test_the_dir_merges_into_an_existing_one(self):
        self.cache_dir_recommendation('trip', {'action': 'move', 'path': 'photos', 'summary': 'photos',
                                               'reason': 'more photos'})
        self.sort([picker.Picked('', 'trip', ['trip/c.jpg']), None],
                  ["Move the dir trip/ (1 file) to Claude's recommendation, into the dir there", YES])
        self.assertTrue(self.exists('sorted', 'photos', 'c.jpg'))
        self.assertTrue(self.exists('sorted', 'photos', 'old.jpg'))

    def test_the_dir_moves_whole_into_a_picked_dir(self):
        self.sort([picker.Picked('', 'trip', ['trip/c.jpg']), None],
                  ["Move the dir trip/ (1 file) into a dir you pick", YES], dirs=[os.path.join(self.root, 'photos')])
        self.assertTrue(self.exists('sorted', 'photos', 'trip', 'c.jpg'))
        self.assertFalse(self.exists('inbox', 'trip'))

    def test_the_dir_moves_whole_into_a_picked_dir_under_a_typed_name(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='rome 2024') as ask:
            self.sort([picker.Picked('', 'trip', ['trip/c.jpg']), None],
                      ["Move the dir trip/ (1 file) into a dir you pick, under a name you type", YES],
                      dirs=[os.path.join(self.root, 'photos')])
        # Starting as its own name
        self.assertEqual(ask.call_args.args[3], 'trip')
        self.assertTrue(self.exists('sorted', 'photos', 'rome 2024', 'c.jpg'))
        self.assertFalse(self.exists('inbox', 'trip'))

    def test_the_dir_is_removed_as_claude_says(self):
        self.cache_dir_recommendation('trip', {'action': 'remove', 'path': '', 'summary': 'copies',
                                               'reason': 'all copies of photos/'})
        with self.fake_gio_trash():
            self.sort([picker.Picked('', 'trip', ['trip/c.jpg']), None],
                      ["Remove the dir trip/ (1 file), as Claude says: all copies of photos/", YES, SURE])
        confirm = self.pick_option.call_args_list[1].kwargs['header']
        self.assertIn("  trip/: all copies of photos/", confirm)
        self.assertEqual(os.listdir(self.trash), ['c.jpg'])

    def test_spread(self):
        self.assertEqual(formatting.spread([1, 2, 3], 5), [1, 2, 3])
        self.assertEqual(formatting.spread(list(range(10)), 4), [0, 3, 6, 9])
        self.assertEqual(formatting.spread(list(range(10)), 1), [0])


if __name__ == '__main__':
    unittest.main()
