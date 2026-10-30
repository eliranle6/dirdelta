import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import ai
from dirdelta import clouddirtree
from dirdelta import inbox
from dirdelta import localdiskdirtree
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

    def synchronously(self):
        """Patch InboxSort.ask_in_background to wait for what it asks Claude, so a test sees it done"""
        ask = Sort.ask_in_background

        def ask_and_wait(sorter, relpaths, place=True):
            ask(sorter, relpaths, place)
            sorter.wait_for_claude()
        return mock.patch.object(Sort, 'ask_in_background', ask_and_wait)

    def sort(self, picks, answers, dirs=(), view=True, is_dry_run=False):
        """Sort, the inbox's picker answering picks in turn, the menus answers, the dir picker
        dirs (paths), and the approval's view returning view"""
        picks, dirs = list(picks), list(dirs)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option, \
                mock.patch('dirdelta.picker.pick_under_dir',
                           side_effect=lambda *_, **__: dirs.pop(0)) as self.pick_under_dir, \
                mock.patch('dirdelta.picker.view_files', return_value=view) as self.view_files, \
                mock.patch('dirdelta.dryrun.DRYRUN', is_dry_run), self.synchronously():
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

    def test_a_move_goes_back_to_the_picker_unless_some_werent_moved(self):
        with mock.patch('dirdelta.messages.progress_screen', wraps=inbox.messages.progress_screen) as screen:
            self.sort([['a.txt'], None], ['Move the 1 file to...', YES], dirs=[os.path.join(self.root, 'docs')])
        self.assertFalse(screen.call_args.kwargs['wait'])
        self.show.assert_not_called()
        # One that's there already is skipped: not moved
        helpers.make_files(self.root, ['docs/b.jpg'])
        self.sort([['b.jpg', 'trip/c.jpg'], None], ['Move the 2 files to...', YES], dirs=[os.path.join(self.root, 'docs')])
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Not all were moved')
        self.assertEqual(lines[1:], ['  b.jpg'])
        self.assertTrue(self.exists('sorted', 'docs', 'c.jpg'))

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

    def test_a_removal_goes_back_to_the_picker_unless_some_werent_removed(self):
        with mock.patch('dirdelta.messages.progress_screen', wraps=inbox.messages.progress_screen) as screen:
            self.sort([['a.txt'], None], ['Remove the 1 file', YES, SURE])
        self.assertFalse(screen.call_args.kwargs['wait'])
        self.show.assert_not_called()
        real_unlink = os.unlink

        def unlink(path):
            if path.endswith('b.jpg'):
                raise PermissionError('read-only')
            real_unlink(path)
        with mock.patch('dirdelta.localdiskdirtree.os.unlink', side_effect=unlink):
            self.sort([['b.jpg', 'trip/c.jpg'], None], ['Remove the 2 files', YES, SURE])
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Not all were removed')
        self.assertEqual(lines[1:], ['  b.jpg'])

    def test_a_dry_run_changes_nothing(self):
        self.sort([['a.txt'], None], ['Move the 1 file to...', YES], dirs=[self.root], is_dry_run=True)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('sorted', 'a.txt'))

    def test_the_menu_starts_with_nothing(self):
        self.sort([['a.txt'], None], [NOTHING])
        options = self.pick_option.call_args.args[0]
        self.assertEqual(options[0], NOTHING)
        self.assertEqual([option.split(' ')[0] for option in options[1:]],
                         ['Describe', 'Ask', 'Move', 'Remove', 'Move', 'Copy', 'Remove'])
        # With nothing recommended yet, those are greyed out
        disabled = self.pick_option.call_args.kwargs['shown_as']()
        self.assertEqual([text.text.split(': ')[-1] for text in disabled.values()],
                         ['none of them has a recommendation to move it yet',
                          'none of them is a copy of a file there (by its contents)'])

    def ask_claude(self, answers):
        """Patch ai._run_query to answer with answers ({relpath: {field: value}}) for the files in its
        prompt, the fields its schema asks for; its calls are self.queries"""
        self.queries = []

        def run_query(prompt, readable_dirs, schema, max_turns, model, system_prompt=None):
            fields = schema['properties']['files']['items']['required'][1:]
            self.queries.append((fields, model, prompt))
            lines = prompt.split('The files')[1].split(':\n', 1)[1].split('\n\n')[0].splitlines()
            relpaths = [line.split('. ', 1)[1].split(' (')[0] for line in lines]
            return {'files': [dict({field: answers[relpath][field] for field in fields}, number=number)
                              for number, relpath in enumerate(relpaths, 1)]}
        return mock.patch('dirdelta.ai._run_query', side_effect=run_query)

    def test_descriptions_are_shown_after_the_names(self):
        with self.ask_claude({'a.txt': {'description': 'a shopping list'}}):
            # Described in the background; quitting waits for it
            self.sort([['a.txt'], None], ['Describe the 1 file'])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(labels, {'a.txt': 'a.txt  | a shopping list', '': ''})
        self.assertEqual(self.queries[0][:2], (['description'], ai.MODEL))
        # Kept: shown on the next run too, without asking
        with mock.patch('dirdelta.ai._run_query', side_effect=AssertionError('asked again')):
            self.sort([None], [])
        self.assertEqual(self.pick_files.call_args.kwargs['shown_as'](), labels)

    def test_files_being_described_say_so(self):
        sorter = Sort(self.inbox, self.root)
        sorter._describing = {'b.jpg'}
        shown = sorter._shown_as(['a.txt', 'b.jpg'])
        self.assertEqual(shown, {'b.jpg': 'b.jpg  | ' + inbox.LOOKING, '': 'Claude: describing 1 file'})
        self.assertIn("Claude is looking at it...", sorter._previews(['b.jpg'])['b.jpg'])

    def test_ctrl_i_describes_the_picked_files_or_the_selected_ones_in_the_background(self):
        with self.ask_claude({'a.txt': {'description': 'a list'}, 'b.jpg': {'description': 'a cat'},
                              'trip/c.jpg': {'description': 'a beach'}}):
            self.sort([None], [])
            kwargs = self.pick_files.call_args.kwargs
            self.assertEqual(kwargs['notify_keys'], '\t')
            kwargs['on_notify']('\t', 'trip', [])
            self.sorter.wait_for_claude()
            self.assertEqual(self.sorter._descriptions, {'trip/c.jpg': 'a beach'})
            kwargs['on_notify']('\t', 'trip/c.jpg', ['a.txt'])
            self.sorter.wait_for_claude()
        self.assertEqual(sorted(self.sorter._descriptions), ['a.txt', 'trip/c.jpg'])

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
        menus = [call.args[0] for call in self.pick_option.call_args_list]
        # One destination: the menu names it
        self.assertIn("Move the 1 file to Claude's recommendation: %s/photos/cats/" % (self.root,), menus[1])
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

    def sent_previews(self, pick_files_call):
        """What a picker's previews sent it first (then the picker is gone)"""
        sent = {}

        def send(found=None, default=None):
            if sent:
                raise picker.PickerClosed()
            sent.update(found or {})
        with self.assertRaises(picker.PickerClosed):
            pick_files_call.kwargs['previews'](send)
        return sent

    def test_the_previews_are_sent_again_as_they_change(self):
        sorter = Sort(self.inbox, self.root)
        sends = []

        def send(found=None, default=None):
            sends.append(dict(found))
            if len(sends) == 1:
                sorter._descriptions['a.txt'] = 'a list'
            elif len(sends) == 3:
                raise picker.PickerClosed()
        with mock.patch('dirdelta.inbox.PREVIEWS_INTERVAL', 0), self.assertRaises(picker.PickerClosed):
            sorter._send_previews(['a.txt', 'b.jpg'], send)
        self.assertEqual(sorted(sends[0]), ['a.txt', 'b.jpg'])
        # Only the one that changed
        self.assertEqual(list(sends[1]), ['a.txt'])
        self.assertIn("  a list", sends[1]['a.txt'])
        self.assertEqual(sends[2], {})

    def copy_in_the_inbox(self):
        """An inbox file with the same name and contents as the sorted tree's docs/old.txt"""
        with open(os.path.join(self.inbox, 'old.txt'), 'w') as f:
            f.write('docs/old.txt')

    def test_a_copy_of_a_sorted_file_is_found_and_said(self):
        self.copy_in_the_inbox()
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['old.txt', 'a.txt'])
        self.assertEqual(sorter._copies('old.txt'), ['docs/old.txt'])
        lines = sorter._previews(['old.txt'])['old.txt']
        self.assertIn("  docs/old.txt", lines)
        self.assertIn(inbox.SURELY_A_COPY, lines)
        # Its hash is kept, for next time
        self.assertIsNotNone(inbox.elsewhere.hashcache.get(os.path.join(self.inbox, 'old.txt'), 'sha1'))

    def test_copies_found_by_contents_can_be_removed_without_claude(self):
        self.copy_in_the_inbox()
        with open(os.path.join(self.inbox, 'b.jpg'), 'w') as f:
            f.write('photos/old.jpg')
        os.rename(os.path.join(self.inbox, 'b.jpg'), os.path.join(self.inbox, 'old.jpg'))
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['old.txt'])
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            sorter._act(['old.txt', 'a.txt', 'old.jpg'])
        option = [option for option in pick_option.call_args.args[0] if option.startswith('Remove 1')][0]
        self.assertEqual(option, "Remove 1 of the 3 files that are copies of files in %s (1 not compared yet: "
                                 "Ctrl-I compares them)" % (self.root,))
        self.assertNotIn(option, pick_option.call_args.kwargs['shown_as']())

    def test_claude_is_told_of_copies_and_its_removals_are_offered(self):
        self.copy_in_the_inbox()
        with self.ask_claude({'old.txt': {'description': 'an old note', 'action': 'remove', 'path': '',
                                          'reason': 'a copy'},
                              'a.txt': {'description': 'a list', 'action': 'move', 'path': 'docs/a.txt',
                                        'reason': 'a list'}}):
            self.sort([['a.txt', 'old.txt'], ['a.txt', 'old.txt'], None],
                      ['Ask Claude', 'Remove 1 of the 2 files that are copies', YES, SURE])
        self.assertIn("already in the sorted tree, with the same contents, at docs/old.txt", self.queries[1][2])
        self.assertIn("  old.txt: a copy of %s/docs/old.txt" % (self.root,),
                      self.pick_option.call_args_list[2].kwargs['header'])
        self.assertFalse(self.exists('inbox', 'old.txt'))
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_the_selected_file_is_compared_in_the_background(self):
        self.sort([None], [])
        on_selection = self.pick_files.call_args.kwargs['on_selection']
        self.assertIs(on_selection.args[4], self.sorter._checked)
        self.assertEqual(on_selection.keywords, {'sends_previews': False})

    def test_claudes_errors_are_said(self):
        with mock.patch('dirdelta.ai._run_query', side_effect=ai.AIError('not logged in')):
            self.sort([['a.txt'], None], ['Describe the 1 file'])
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

    def test_files_being_placed_say_so(self):
        sorter = Sort(self.inbox, self.root)
        sorter._placing = {'b.jpg'}
        sorter._descriptions = {'b.jpg': 'a cat'}
        self.assertEqual(sorter._shown_as(['b.jpg'])[''], 'Claude: placing 1 file')
        self.assertIn("Claude is working out where", sorter._previews(['b.jpg'])['b.jpg'])

    def test_the_sorted_trees_dirs_for_claude_leave_the_inbox_out(self):
        os.makedirs(os.path.join(self.root, 'unsorted', 'deep'))
        sorter = Sort(os.path.join(self.root, 'unsorted'), self.root)
        self.assertEqual(sorter._root_dirs(), {'': [], 'docs': ['old.txt'], 'photos': ['old.jpg']})

    def test_bad_pairs_are_refused(self):
        with self.assertRaises(inbox.InboxError):
            Sort(self.inbox, os.path.join(self.inbox, 'trip'))
        with self.assertRaises(inbox.InboxError):
            Sort(os.path.join(self.tmpdir, 'nope'), self.root)

    def test_a_dir_in_the_inbox_cant_be_the_destination(self):
        root_with_inbox = self.tmpdir
        sorter = Sort(self.inbox, root_with_inbox)
        with mock.patch('dirdelta.picker.pick_under_dir', return_value=os.path.join(self.inbox, 'trip')):
            self.assertIsNone(sorter._pick_dir('Pick'))
        self.assertEqual(self.show.call_args.args[0], "That's the inbox")

    def two_trees(self):
        """The sort with a tree each (as a local inbox and a Drive sorted tree have), both local
        here, so the copy-then-remove path is run without Drive"""
        sorter = Sort(self.inbox, self.root)
        sorter.is_one_tree = False
        sorter._inbox_tree = localdiskdirtree.LocalDiskDirTree(self.inbox, silent=True)
        sorter._root_tree = localdiskdirtree.LocalDiskDirTree(self.root, silent=True)
        sorter._inbox_rel = sorter._root_rel = ''
        sorter._inbox_tree.keep_dirs([''])
        return sorter

    def test_a_move_between_two_trees_is_a_copy_then_a_removal(self):
        sorter = self.two_trees()
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
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
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.shutil.copy2', side_effect=copy):
            done = sorter._transfer([('a.txt', 'docs/a.txt'), ('b.jpg', 'photos/b.jpg')], True)
        self.assertEqual(done, [('b.jpg', 'photos/b.jpg')])
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('inbox', 'b.jpg'))

    def test_a_copy_between_two_trees_keeps_the_inbox_files(self):
        sorter = self.two_trees()
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            sorter._transfer([('a.txt', 'docs/a.txt')], False)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))

    def test_a_dry_run_between_two_trees_changes_nothing(self):
        sorter = self.two_trees()
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.assertEqual(sorter._transfer([('a.txt', 'docs/a.txt')], True), [])
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('sorted', 'docs', 'a.txt'))

    def test_a_local_inbox_and_a_drive_sorted_tree_get_a_tree_each(self):
        cache = os.path.join(self.tmpdir, 'files.txt')
        with open(cache, 'w') as f:
            f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            f.write(json.dumps({'id': 'me', 'name': 'me', 'parents': ['ROOT'],
                                'mimeType': 'application/vnd.google-apps.folder'}) + '\n')
        with mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', cache):
            sorter = Sort(self.inbox, 'cloud/me')
            with self.assertRaises(inbox.drivecache.DriveCacheError):
                Sort(self.inbox, 'cloud/nope')
        self.assertFalse(sorter.is_one_tree)
        self.assertIsInstance(sorter._root_tree, clouddirtree.CloudDirTree)
        self.assertEqual(sorter._inbox_tree.fullpath(), self.inbox)
        self.assertEqual(sorter.root_path, 'cloud/me')

    def test_run_records_the_sort(self):
        known = replicas.Replicas()
        with mock.patch('dirdelta.replicas.save') as save, \
                mock.patch.object(Sort, 'run'):
            inbox.run(self.inbox, self.root, known)
        self.assertEqual(known.sorts, [(self.inbox, self.root)])
        save.assert_called_once_with(known)


if __name__ == '__main__':
    unittest.main()
