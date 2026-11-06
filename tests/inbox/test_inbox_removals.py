"""Removing the inbox's files: asked twice, junk, and copies of the sorted tree's files"""
import os
import unittest
from unittest import mock

import helpers
from dirdelta.hashes import hashcache
from dirdelta.hashes import hashing
from dirdelta.inbox import constants
from dirdelta.ui import messages
from dirdelta.ui import picker
from inbox_support import InboxSortTest, NO, NOTHING, SURE, Sort, YES


class RemovalsTest(InboxSortTest):
    """Removals, junk and copies"""

    def test_junk_by_name_is_shown_and_removed_to_the_trash(self):
        helpers.make_files(self.inbox, ['Thumbs.db', 'trip/~$plan.docx'])
        self.sort([None], [])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(picker.unstyled(labels['Thumbs.db']), 'Thumbs.db  [junk? a Windows thumbnails cache]')
        # The junk's tag in a guess's yellow
        self.assertEqual(labels['Thumbs.db'], picker.styled([('Thumbs.db', None), ('  ', None),
                                                             ('[junk? a Windows thumbnails cache]', 'yellow')]))
        self.assertNotIn('a.txt', labels)
        preview = self.sent_previews(self.pick_files.call_args)['Thumbs.db']
        self.assertIn(constants.MAYBE_JUNK, preview)
        with self.fake_gio_trash():
            self.sort([['a.txt', 'Thumbs.db', 'trip/~$plan.docx'], None],
                      ['Remove 2 of the 3 files: they look like junk (to the trash)', YES, SURE])
        # Listed with why, and asked twice, the second time saying where they go
        confirm, sure = [call.kwargs['header'] for call in self.pick_option.call_args_list[1:3]]
        self.assertIn("  Thumbs.db: a Windows thumbnails cache", confirm)
        self.assertIn("(to the trash)", sure)
        self.assertEqual(sorted(os.listdir(self.trash)), ['Thumbs.db', '~$plan.docx'])
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_junk_as_claude_says(self):
        with self.ask_claude({'a.txt': {'description': 'an empty note', 'action': 'remove', 'path': '',
                                        'reason': 'an empty note'}}):
            self.sort([['a.txt'], ['a.txt'], None], ['Ask Claude', NOTHING])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(picker.unstyled(labels['a.txt']), 'a.txt  [claude: an empty note]  [claude: junk? an empty note]')
        menu = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertIn('Remove it: it looks like junk (to the trash)', menu)

    def test_remove_is_asked_twice(self):
        self.sort([['a.txt'], None], ['Remove it from', YES, SURE])
        self.assertFalse(self.exists('inbox', 'a.txt'))
        self.assertEqual(helpers.labels_of(self.pick_option.call_args.args[0]), [NO, SURE])
        self.sort([['b.jpg'], None], ['Remove it from', YES, NO])
        self.assertTrue(self.exists('inbox', 'b.jpg'))

    def test_a_removal_waits_for_enter_and_says_if_some_werent_removed(self):
        with mock.patch('dirdelta.ui.messages.progress_screen', wraps=messages.progress_screen) as screen:
            self.sort([['a.txt'], None], ['Remove it from', YES, SURE])
        # "Press Enter to continue" once it's done
        self.assertNotIn('wait', screen.call_args.kwargs)
        self.show.assert_not_called()
        real_unlink = os.unlink

        def unlink(path):
            if path.endswith('b.jpg'):
                raise PermissionError('read-only')
            real_unlink(path)
        with mock.patch('dirdelta.trees.localdiskdirtree.fs.os.unlink', side_effect=unlink):
            self.sort([['b.jpg', 'trip/c.jpg'], None], ['Remove the 2 files from', YES, SURE])
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Not all were removed')
        self.assertEqual(lines[1:], ['  b.jpg'])

    def test_a_copy_of_a_sorted_file_is_found_and_said(self):
        self.copy_in_the_inbox()
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['old.txt', 'a.txt'])
        self.assertEqual(sorter._copies('old.txt'), ['docs/old.txt'])
        lines = sorter._previews(['old.txt'])['old.txt']
        title = lines.index(picker.styled([(constants.IN_SORTED_TREE_TITLE + " ", 'bold,magenta'), ("Yes", 'bold,green')]))
        self.assertEqual(''.join(line.strip() for line in lines[title + 1:lines.index(constants.SURELY_A_COPY)]),
                         os.path.join(self.root, 'docs', 'old.txt'))
        self.assertIn(constants.SURELY_A_COPY, lines)
        # Its hash is kept, for next time
        self.assertIsNotNone(hashcache.get(os.path.join(self.inbox, 'old.txt'), 'sha1'))

    def test_copies_found_by_contents_can_be_removed_without_claude(self):
        self.copy_in_the_inbox()
        with open(os.path.join(self.inbox, 'b.jpg'), 'w') as f:
            f.write('photos/old.jpg')
        os.rename(os.path.join(self.inbox, 'b.jpg'), os.path.join(self.inbox, 'old.jpg'))
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['old.txt'])
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            sorter._act(['old.txt', 'a.txt', 'old.jpg'])
        option = [option for option in helpers.labels_of(pick_option.call_args.args[0]) if option.startswith('Remove 1')][0]
        self.assertEqual(option, "Remove 1 of the 3 files: copies of files in %s (1 not compared yet: "
                                 "Ctrl-I compares them)" % (self.root,))

    def test_a_copys_plain_removal_isnt_offered_as_well(self):
        # Removing it from the inbox would do what removing the copy does
        self.copy_in_the_inbox()
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['old.txt'])
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            sorter._act(['old.txt'])
        removals = [option for option in helpers.labels_of(pick_option.call_args.args[0]) if option.startswith('Remove')]
        self.assertEqual(removals, ["Remove it: a copy of a file in %s" % (self.root,)])
        # With a file that isn't a copy, both are
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            sorter._act(['old.txt', 'a.txt'])
        removals = [option for option in helpers.labels_of(pick_option.call_args.args[0]) if option.startswith('Remove')]
        self.assertEqual(len(removals), 2)

    def test_a_renamed_copy_is_found_by_the_hashes_of_both_with_nothing_compared(self):
        # a.txt's contents, under another name, in the sorted tree
        helpers.make_files(self.root, ['docs/renamed'])
        with open(os.path.join(self.root, 'docs', 'renamed'), 'w') as f:
            f.write('a.txt')
        sorter = Sort(self.inbox, self.root)
        for path in (self.inbox, self.root):
            job = hashing.job(path)
            self.addCleanup(hashing.registry._jobs.pop, job.root, None)
            job.scan()
            job._is_started = True
            for relpath in job.files():
                if job._take(relpath):
                    job._hash(relpath)
        self.assertEqual(sorter._copies('a.txt'), ['docs/renamed'])
        self.assertEqual(sorter._checked, {})
        # Marked as hashed in the picker, with how far each got on the bottom line
        shown = sorter._shown_as(['a.txt'])
        self.assertEqual(picker.unstyled(shown['a.txt']), 'a.txt  ' + hashing.HASHED_TAG)
        self.assertIn('inbox: 100% hashed', shown[''])

    def test_claude_is_told_of_copies_and_its_removals_are_offered(self):
        self.copy_in_the_inbox()
        with self.ask_claude({'old.txt': {'description': 'an old note', 'action': 'remove', 'path': '',
                                          'reason': 'a copy'},
                              'a.txt': {'description': 'a list', 'action': 'move', 'path': 'docs/a.txt',
                                        'reason': 'a list'}}):
            self.sort([['a.txt', 'old.txt'], ['a.txt', 'old.txt'], None],
                      ['Ask Claude', 'Remove 1 of the 2 files: copies', YES, SURE])
        self.assertIn("already in the sorted tree, with the same contents, at docs/old.txt", self.queries[1][2])
        self.assertIn("  old.txt: a copy of %s/docs/old.txt" % (self.root,),
                      self.pick_option.call_args_list[2].kwargs['header'])
        self.assertFalse(self.exists('inbox', 'old.txt'))
        self.assertTrue(self.exists('inbox', 'a.txt'))


if __name__ == '__main__':
    unittest.main()
