import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import ai
from dirdelta import inbox
from dirdelta import picker
from dirdelta import replicas

Sort = inbox.InboxSort
NOTHING = Sort.NOTHING
YES = Sort.CONFIRM_YES
NO = Sort.CONFIRM_NO
SURE = Sort.CONFIRM_SURE


class InboxSortTest(unittest.TestCase):
    """A local inbox with a.txt, b.jpg and trip/c.jpg; a sorted tree with docs/ and photos/"""

    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-inbox-'))
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.inbox = os.path.join(self.tmpdir, 'inbox')
        self.root = os.path.join(self.tmpdir, 'sorted')
        helpers.make_files(self.inbox, ['a.txt', 'b.jpg', 'trip/c.jpg'])
        helpers.make_files(self.root, ['docs/old.txt', 'photos/old.jpg'])
        for patcher in (mock.patch('dirdelta.messages.print_line'),
                        mock.patch('dirdelta.messages.print_progress'),
                        mock.patch('dirdelta.messages.show'),
                        mock.patch('dirdelta.ai.CACHE_FILE', os.path.join(self.tmpdir, 'ai.json'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show = inbox.messages.show

    def sort(self, picks, answers, dirs=(), view=True, is_dry_run=False):
        """Sort, the inbox's picker answering picks in turn, the menus answers, the dir picker
        dirs (paths), and the approval's view returning view"""
        picks, dirs = list(picks), list(dirs)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option, \
                mock.patch('dirdelta.picker.pick_under_dir',
                           side_effect=lambda *_, **__: dirs.pop(0)) as self.pick_under_dir, \
                mock.patch('dirdelta.picker.view_files', return_value=view) as self.view_files, \
                mock.patch('dirdelta.dryrun.DRYRUN', is_dry_run):
            self.sorter = Sort(self.inbox, self.root)
            self.sorter.run()

    def exists(self, *parts):
        return os.path.exists(os.path.join(self.tmpdir, *parts))

    def test_move_to_a_picked_dir(self):
        self.sort([['a.txt'], None], ['Move the 1 file to...', YES], dirs=[os.path.join(self.root, 'docs')])
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))
        self.assertFalse(self.exists('inbox', 'a.txt'))
        # The dir picker: the sorted tree's dirs, read as shown
        args, kwargs = self.pick_under_dir.call_args
        self.assertEqual(args, (self.root,))
        self.assertTrue(kwargs['dirs_only'] and kwargs['lazy'])
        # Back to the files left
        self.assertEqual(self.pick_files.call_args.args[1], ['b.jpg', 'trip/c.jpg'])

    def test_the_approval_shows_the_tree_it_makes(self):
        self.sort([['a.txt', 'trip/c.jpg'], None], ['Move the 2 files to...', YES],
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
        self.sort([['a.txt'], None], ['Move the 1 file to...'], dirs=[os.path.join(self.root, 'docs')],
                  view=False)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['a.txt'])

    def test_files_of_the_same_name_to_one_dir_are_refused(self):
        helpers.make_files(self.inbox, ['other/a.txt'])
        self.sort([['a.txt', 'other/a.txt'], None], ['Move the 2 files to...'], dirs=[self.root])
        self.assertEqual(self.show.call_args.args[0], 'Files of the same name')
        self.view_files.assert_not_called()

    def test_the_inbox_is_kept_when_emptied(self):
        self.sort([['a.txt', 'b.jpg', 'trip/c.jpg']], ['Move the 3 files to...', YES], dirs=[self.root])
        self.assertTrue(os.path.isdir(self.inbox))
        self.assertEqual(os.listdir(self.inbox), [])
        self.assertEqual(self.show.call_args.args[0], 'The inbox is empty')

    def test_copy_keeps_the_inbox_file(self):
        self.sort([['b.jpg'], None], ['Copy the 1 file to...', YES], dirs=[os.path.join(self.root, 'photos')])
        self.assertTrue(self.exists('sorted', 'photos', 'b.jpg'))
        self.assertTrue(self.exists('inbox', 'b.jpg'))
        # Done, so no longer picked
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], [])

    def test_remove_is_asked_twice(self):
        self.sort([['a.txt'], None], ['Remove the 1 file', YES, SURE])
        self.assertFalse(self.exists('inbox', 'a.txt'))
        self.assertEqual(self.pick_option.call_args.args[0], [NO, SURE])
        self.sort([['b.jpg'], None], ['Remove the 1 file', YES, NO])
        self.assertTrue(self.exists('inbox', 'b.jpg'))

    def test_a_dry_run_changes_nothing(self):
        self.sort([['a.txt'], None], ['Move the 1 file to...', YES], dirs=[self.root], is_dry_run=True)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('sorted', 'a.txt'))

    def test_the_menu_starts_with_nothing(self):
        self.sort([['a.txt'], None], [NOTHING])
        options = self.pick_option.call_args.args[0]
        self.assertEqual(options[0], NOTHING)
        self.assertEqual([option.split(' ')[0] for option in options[1:]],
                         ['Describe', 'Ask', 'Move', 'Move', 'Copy', 'Remove'])
        # With nothing recommended yet, that move is greyed out
        disabled = self.pick_option.call_args.kwargs['shown_as']()
        self.assertEqual([text.text.split(':')[-1].strip() for text in disabled.values()],
                         ['none of them has a recommendation yet'])

    def ask_claude(self, answers):
        """Patch ai._run_query to answer with answers ({relpath: answer}) for the files in its prompt"""
        def run_query(prompt, readable_dirs, schema, max_turns, model):
            lines = prompt.split('The files:\n')[1].splitlines()
            return {'files': [dict(answers[line.split('. ', 1)[1].split(' (')[0]], number=number)
                              for number, line in enumerate(lines, 1)]}
        return mock.patch('dirdelta.ai._run_query', side_effect=run_query)

    def test_descriptions_are_shown_after_the_names(self):
        with self.ask_claude({'a.txt': {'description': 'a shopping list'}}):
            self.sort([['a.txt'], None], ['Describe 1 file'])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(labels, {'a.txt': 'a.txt  | a shopping list'})
        # Kept: shown on the next run too, without asking
        with mock.patch('dirdelta.ai._run_query', side_effect=AssertionError('asked again')):
            self.sort([None], [])
        self.assertEqual(self.pick_files.call_args.kwargs['shown_as'](), labels)

    def test_recommendations_are_shown_and_moved_to(self):
        with self.ask_claude({'b.jpg': {'description': 'a cat', 'destination': 'photos/cats', 'reason': 'a cat photo'},
                              'trip/c.jpg': {'description': 'a beach', 'destination': 'photos/trips/2024',
                                             'reason': 'a trip photo'}}):
            self.sort([['b.jpg', 'trip/c.jpg'], ['b.jpg'], ['b.jpg', 'trip/c.jpg'], None],
                      ['Ask Claude', NOTHING, "Move the 2 files to Claude's recommendations (2 dirs)", YES])
        # The prompt had the sorted tree's dirs (not the inbox's)
        menus = [call.args[0] for call in self.pick_option.call_args_list]
        # One destination: the menu names it
        self.assertIn("Move the 1 file to Claude's recommendation: %s/photos/cats/" % (self.root,), menus[1])
        self.assertTrue(self.exists('sorted', 'photos', 'cats', 'b.jpg'))
        self.assertTrue(self.exists('sorted', 'photos', 'trips', '2024', 'c.jpg'))
        lines = self.pick_files.call_args_list[1].kwargs['previews']
        sent = {}
        lines(lambda found=None, default=None: sent.update(found or {}))
        self.assertIn("  photos/cats/", sent['b.jpg'])

    def test_claudes_errors_are_said(self):
        with mock.patch('dirdelta.ai._run_query', side_effect=ai.AIError('not logged in')):
            self.sort([['a.txt'], None], ['Describe 1 file'])
        inbox.messages.print_line.assert_any_call('not logged in', 'red')

    def test_the_sorted_trees_dirs_for_claude_leave_the_inbox_out(self):
        os.makedirs(os.path.join(self.root, 'unsorted', 'deep'))
        sorter = Sort(os.path.join(self.root, 'unsorted'), self.root)
        self.assertEqual(sorted(sorter._root_dirs()), ['docs', 'photos'])

    def test_bad_pairs_are_refused(self):
        with self.assertRaises(inbox.InboxError):
            Sort(self.inbox, os.path.join(self.inbox, 'trip'))
        with self.assertRaises(inbox.InboxError):
            Sort(self.inbox, 'cloud/me')
        with self.assertRaises(inbox.InboxError):
            Sort(os.path.join(self.tmpdir, 'nope'), self.root)

    def test_a_dir_in_the_inbox_cant_be_the_destination(self):
        root_with_inbox = self.tmpdir
        sorter = Sort(self.inbox, root_with_inbox)
        with mock.patch('dirdelta.picker.pick_under_dir', return_value=os.path.join(self.inbox, 'trip')):
            self.assertIsNone(sorter._pick_dir('Pick'))
        self.assertEqual(self.show.call_args.args[0], "That's the inbox")

    def test_run_records_the_sort(self):
        known = replicas.Replicas()
        with mock.patch('dirdelta.replicas.save') as save, \
                mock.patch.object(Sort, 'run'):
            inbox.run(self.inbox, self.root, known)
        self.assertEqual(known.sorts, [(self.inbox, self.root)])
        save.assert_called_once_with(known)


if __name__ == '__main__':
    unittest.main()
