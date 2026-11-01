import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

import helpers
from dirdelta import ai
from dirdelta import clouddirtree
from dirdelta import inbox
from dirdelta import localdiskdirtree
from dirdelta import picker
from dirdelta import replicalog
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

        def ask_and_wait(sorter, relpaths, place=True, anew=False):
            ask(sorter, relpaths, place, anew)
            sorter.wait_for_claude()
        return mock.patch.object(Sort, 'ask_in_background', ask_and_wait)

    def sort(self, picks, answers, dirs=(), view=True, is_dry_run=False, known=None):
        """Sort, the inbox's picker answering picks in turn, the menus answers, the dir picker
        dirs (paths), and the approval's view returning view"""
        picks, dirs = list(picks), list(dirs)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option, \
                mock.patch('dirdelta.picker.pick_under_dir',
                           side_effect=lambda *_, **__: self.picked_dir(dirs.pop(0))) as self.pick_under_dir, \
                mock.patch('dirdelta.picker.view_files', return_value=view) as self.view_files, \
                mock.patch('dirdelta.dryrun.DRYRUN', is_dry_run), self.synchronously():
            self.sorter = Sort(self.inbox, self.root, known)
            self.sorter.run()

    @staticmethod
    def picked_dir(picked):
        """What the dir picker returns for picked: a path (Enter on it), or (a key, the path)"""
        return picked if isinstance(picked, tuple) else ('', picked)

    def exists(self, *parts):
        return os.path.exists(os.path.join(self.tmpdir, *parts))

    def test_a_move_stopped_with_ctrl_c_says_what_was_left(self):
        # Stopped while transferring, before it said what it did: what's there now is what was done
        def stopped(*_, **__):
            raise KeyboardInterrupt()
        with mock.patch.object(Sort, '_transfer', side_effect=stopped), \
                mock.patch('dirdelta.localdiskdirtree.LocalDiskDirTree.move_files', side_effect=stopped):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')],
                      is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertEqual(self.show.call_args.args[0], 'Not all were moved')

    def test_o_makes_a_new_dir_beside_the_selected_one(self):
        with mock.patch('dirdelta.messages.ask', return_value='letters'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[('o', os.path.join(self.root, 'docs'))], is_dry_run=False)
        # In docs/'s dir, the root, not in docs/
        self.assertTrue(self.exists('sorted', 'letters', 'a.txt'))
        keys = self.pick_under_dir.call_args.kwargs['keys']
        self.assertIn('o', keys)
        self.assertIn('O', keys)

    def test_files_are_moved_to_another_dir_of_the_inbox(self):
        with mock.patch('dirdelta.messages.ask', return_value='lists'):
            self.sort([['a.txt'], None], ['Move it to another dir in the inbox', YES],
                      dirs=[('n', self.inbox)], is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'lists', 'a.txt'))
        self.assertFalse(self.exists('inbox', 'a.txt'))
        # Picked from the inbox's dirs
        self.assertEqual(self.pick_under_dir.call_args.args[0], self.inbox)

    def test_whats_known_goes_with_a_file_moved_in_the_inbox(self):
        sorter = Sort(self.inbox, self.root)
        sorter._descriptions['a.txt'] = 'a list'
        with helpers.answering_option_picker([YES]), mock.patch('dirdelta.dryrun.DRYRUN', False):
            self.assertEqual(sorter._move_in_inbox(['a.txt'], 'trip'), ['a.txt'])
        self.assertEqual(sorter._descriptions, {'trip/a.txt': 'a list'})
        # Already there: nothing to move
        self.assertIsNone(sorter._move_in_inbox(['trip/a.txt'], 'trip'))

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
        with mock.patch('dirdelta.messages.progress_screen', wraps=inbox.messages.progress_screen) as screen:
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

    def fake_gio_trash(self):
        """Patch subprocess.run so gio trash moves the file into self.trash (anything else runs)"""
        self.trash = os.path.join(self.tmpdir, 'trash')
        os.makedirs(self.trash)
        real_run = subprocess.run

        def run(command, *args, **kwargs):
            if command[:2] == ['gio', 'trash']:
                shutil.move(command[2], self.trash)
                return subprocess.CompletedProcess(command, 0, stdout='')
            return real_run(command, *args, **kwargs)
        return mock.patch('subprocess.run', side_effect=run)

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
        self.assertIn(inbox.MAYBE_JUNK, preview)
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
        menu = self.pick_option.call_args.args[0]
        self.assertIn('Remove it: it looks like junk (to the trash)', menu)

    def test_junk_in_a_dry_run_stays(self):
        helpers.make_files(self.inbox, ['Thumbs.db'])
        with self.fake_gio_trash() as run:
            self.sort([['Thumbs.db'], None], ['Remove it: it looks like junk', YES, SURE], is_dry_run=True)
        self.assertTrue(self.exists('inbox', 'Thumbs.db'))
        self.assertFalse([call for call in run.call_args_list if call.args[0][:1] == ['gio']])

    def test_live_changes_are_noted_for_the_logs(self):
        with mock.patch('dirdelta.messages.ask', return_value='x'):
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
                helpers.answering_option_picker(['Move it to a dir you pick', YES, 'Add it to its', replicalog.NO_ENTRY]) as pick, \
                mock.patch('dirdelta.picker.pick_under_dir', return_value=('', os.path.join(self.root, 'docs'))), \
                mock.patch('dirdelta.picker.view_files', return_value=True), \
                mock.patch('dirdelta.replicas.save'), mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.replicalog.identity', side_effect=lambda path: 'id:' + path), \
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

    def test_remove_is_asked_twice(self):
        self.sort([['a.txt'], None], ['Remove it from', YES, SURE])
        self.assertFalse(self.exists('inbox', 'a.txt'))
        self.assertEqual(self.pick_option.call_args.args[0], [NO, SURE])
        self.sort([['b.jpg'], None], ['Remove it from', YES, NO])
        self.assertTrue(self.exists('inbox', 'b.jpg'))

    def test_a_removal_waits_for_enter_and_says_if_some_werent_removed(self):
        with mock.patch('dirdelta.messages.progress_screen', wraps=inbox.messages.progress_screen) as screen:
            self.sort([['a.txt'], None], ['Remove it from', YES, SURE])
        # "Press Enter to continue" once it's done
        self.assertNotIn('wait', screen.call_args.kwargs)
        self.show.assert_not_called()
        real_unlink = os.unlink

        def unlink(path):
            if path.endswith('b.jpg'):
                raise PermissionError('read-only')
            real_unlink(path)
        with mock.patch('dirdelta.localdiskdirtree.os.unlink', side_effect=unlink):
            self.sort([['b.jpg', 'trip/c.jpg'], None], ['Remove the 2 files from', YES, SURE])
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Not all were removed')
        self.assertEqual(lines[1:], ['  b.jpg'])

    def test_a_dry_run_changes_nothing(self):
        self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[self.root], is_dry_run=True)
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.assertFalse(self.exists('sorted', 'a.txt'))

    def ask_ai(self, steps, picks, answers=()):
        """Sort, the inbox's picker answering picks, then the review keeping all, the AI answering steps"""
        picks = list(picks)

        def pick_files(root, items, **_):
            if root == "The AI's plan":
                self.reviewed = list(items)
                return picker.Picked('', '', list(items))
            chosen = picks.pop(0)
            return picker.Picked('', '', chosen) if isinstance(chosen, list) else chosen
        with mock.patch('dirdelta.ai._run_query', return_value={'summary': 'ok', 'steps': steps}), \
                mock.patch('dirdelta.messages.ask', return_value='sort them'), \
                mock.patch('dirdelta.picker.pick_files', side_effect=pick_files), \
                helpers.answering_option_picker(answers), mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.LocalDiskDirTree.trashing', return_value=contextlib.nullcontext()), \
                mock.patch('dirdelta.picker.view_files') as self.view_files:
            self.sorter = Sort(self.inbox, self.root)
            self.sorter.run()

    def test_ask_ai_with_nothing_picked_does_what_the_user_approves_of_all_the_files(self):
        self.ask_ai([{'action': Sort.MOVE_TO, 'number': 1, 'path': 'docs/a2.txt', 'reason': 'a doc'},
                     {'action': Sort.COPY_TO, 'number': 2, 'path': 'photos/b.jpg', 'reason': 'a photo'},
                     {'action': Sort.MOVE_IN_INBOX, 'number': 3, 'path': 'c2.jpg', 'reason': 'neater'}],
                    [picker.Picked('a', '', []), None], [YES, YES, YES])
        self.assertTrue(self.exists('sorted', 'docs', 'a2.txt'))
        self.assertFalse(self.exists('inbox', 'a.txt'))
        self.assertTrue(self.exists('sorted', 'photos', 'b.jpg'))
        self.assertTrue(self.exists('inbox', 'b.jpg'))
        self.assertTrue(self.exists('inbox', 'c2.jpg'))
        # Its own review, not the approval's as well
        self.view_files.assert_not_called()

    def test_ask_ai_in_the_menu_is_about_the_picked_ones(self):
        self.ask_ai([{'action': Sort.REMOVE, 'number': 1, 'reason': 'junk'},
                     {'action': Sort.REMOVE, 'number': 2, 'reason': 'not told of it'}],
                    [['b.jpg'], None], ['Ask AI', YES, 'Yes, remove them'])
        self.assertEqual(self.reviewed, ['Remove from the inbox/b.jpg'])
        self.assertFalse(self.exists('inbox', 'b.jpg'))
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_ask_ai_cant_put_a_file_where_one_is_or_in_the_inbox(self):
        helpers.make_files(self.root, ['docs/a.txt'])
        self.ask_ai([{'action': Sort.MOVE_TO, 'number': 1, 'path': 'docs/a.txt', 'reason': ''},
                     {'action': Sort.MOVE_TO, 'number': 2, 'path': 'photos/b.jpg', 'reason': ''}],
                    [picker.Picked('a', '', []), None], [YES])
        self.assertEqual(self.reviewed, ['Move to the sorted tree/b.jpg'])

    def test_a_zip_is_explored(self):
        with zipfile.ZipFile(os.path.join(self.inbox, 'z.zip'), 'w') as archive:
            archive.writestr('in/side.txt', 'hello')
        self.sort([picker.Picked('e', 'z.zip', []), None], [])
        self.assertEqual(self.view_files.call_args.args[1], ['in/side.txt'])

    def test_ask_ai_is_told_whats_in_the_zip_its_on(self):
        with zipfile.ZipFile(os.path.join(self.inbox, 'z.zip'), 'w') as archive:
            archive.writestr('in/side.txt', 'hello')
        with mock.patch('dirdelta.ai._run_query', return_value={'summary': '', 'answer': 'A text file', 'steps': []}) as query, \
                mock.patch('dirdelta.messages.ask', return_value="what's in this zip?"):
            self.sort([picker.Picked('a', 'z.zip', []), None], [])
        prompt, readable_dirs = query.call_args.args[:2]
        self.assertIn("They're on z.zip", prompt)
        self.assertIn('in/side.txt', prompt)
        self.assertEqual(readable_dirs, [])
        self.assertEqual(self.show.call_args.args[:2], ('The AI says', ['A text file']))

    def test_the_context_menu_with_nothing_picked(self):
        self.sort([picker.Picked(':', 'a.txt', []), None], [NOTHING])
        options = self.pick_option.call_args.args[0]
        for start in ("Choose what to do with a.txt", "Pick a.txt", "Ask AI", "Have Claude describe a.txt",
                      "Open a.txt", "Rename a.txt", "Replicas dashboard"):
            self.assertTrue(any(option.startswith(start) for option in options), start)

    def test_the_context_menu_can_ask_claude(self):
        with mock.patch.object(Sort, '_on_key') as on_key:
            self.sort([picker.Picked(':', 'trip', []), None], ["Have Claude describe"])
        self.assertEqual(on_key.call_args.args[:3], (inbox.DESCRIBE_KEY, 'trip', []))

    def test_the_context_menu_goes_to_enters_menu_of_the_selected_one(self):
        with mock.patch.object(Sort, '_act', return_value=None) as act:
            self.sort([picker.Picked(':', 'trip', []), None], ["Choose what to do"])
        act.assert_called_once_with(['trip/c.jpg'], 'trip')

    def test_with_files_picked_the_key_is_enters_menu(self):
        with mock.patch.object(Sort, '_act', return_value=None) as act:
            self.sort([picker.Picked(':', 'a.txt', ['b.jpg']), None], [])
        act.assert_called_once_with(['b.jpg'], 'a.txt')

    def test_the_menu_starts_with_nothing(self):
        self.sort([['a.txt'], None], [NOTHING])
        # Each kind of action apart, after a blank line (skipped when moving)
        with_blanks = self.pick_option.call_args.args[0]
        self.assertEqual([option.split(' ')[0] if option.strip() else '' for option in with_blanks],
                         ['Nothing:', '', 'Ask', 'Describe', 'Ask', '', 'Move', 'Move', 'Move', '', 'Copy', '', 'Remove', '', 'Open'])
        self.assertTrue(all(self.pick_option.call_args.kwargs['shown_as']()[blank] == picker.Skipped('')
                            for blank in with_blanks if not blank.strip()))
        options = [option for option in with_blanks if option.strip()]
        self.assertEqual(options[0], NOTHING)
        # With nothing recommended yet, and no copies or junk, only what can be done is offered
        self.assertEqual(options[1:], [
            "Ask AI what to do with it, and review its plan",
            "Describe it with Claude, while you go on (sends it their contents)",
            "Ask Claude where it goes in %s, while you go on" % (self.root,),
            "Move it to a dir you pick: %s/<a dir you pick>/a.txt" % (self.root,),
            "Move it to a dir you pick, under a name you type: %s/<a dir you pick>/<a name you type>" % (self.root,),
            "Move it to another dir in the inbox, a dir you pick: %s/<a dir you pick>/a.txt" % (self.inbox,),
            "Copy it to a dir you pick (keeping it in the inbox): %s/<a dir you pick>/a.txt" % (self.root,),
            "Remove it from %s" % (self.inbox,),
            # What the picker's keys do on it (a local inbox isn't read from Drive)
            "Open it with its program"])
        # One file: its name in the header
        self.assertEqual(self.pick_option.call_args.kwargs['header'], "a.txt, in %s: what to do with it?" % (self.inbox,))
        # Each colored by what it does, and where the files go in their sources' colors, after
        # the picker's key that does it, if one does
        shown = self.pick_option.call_args.kwargs['shown_as']()
        self.assertEqual([picker.unstyled(shown[option])[:9] for option in options],
                         [' ' * 9, '[a]      ', ' ' * 9, '[Ctrl-I] '] + [' ' * 9] * 6)
        self.assertEqual(shown[options[3]], picker.styled([('[Ctrl-I]', 'bold'), (' ', None), (options[3], 'magenta')]))
        self.assertEqual(shown[options[4]], ' ' * 9 + picker.styled([
            ("Move it to ", 'blue'), ("a dir you pick", 'yellow'), (": ", 'blue'), (self.root + '/', None),
            ("<a dir you pick>/", 'yellow'), ("a.txt", 'green')]))
        self.assertEqual(shown[options[5]], ' ' * 9 + picker.styled([
            ("Move it to ", 'blue'), ("a dir you pick", 'yellow'), (", ", 'blue'), ("under a name you type", 'yellow'),
            (": ", 'blue'), (self.root + '/', None), ("<a dir you pick>/", 'yellow'), ("<a name you type>", 'yellow')]))
        self.assertTrue(shown[options[7]].startswith(' ' * 9 + picker.styled([
            ("Copy it to ", 'cyan'), ("a dir you pick", 'yellow'), (" (keeping it in the inbox): ", 'cyan')])))
        # And below the menu, what it does and where to, and where each part of the path is from
        lines = self.pick_option.call_args.kwargs['previews_below'][options[4]]
        self.assertEqual(lines[0], picker.segments([(" MOVE ", 'blue'), (" ", None), (self.root + '/', None),
                                                    ("<a dir you pick>/", None), ("a.txt", None)]))
        width = picker.display_width
        self.assertEqual(lines[1], picker.segments([
            (" " * 7, None), (inbox._bracket(("sorted tree",), width(self.root + '/')), None),
            (inbox._bracket(("your pick",), width("<a dir you pick>/")), 'yellow'),
            # The shortest name that fits
            ("[own]", 'green')]))

    def test_claudes_dir_under_the_files_own_name_isnt_offered_when_its_claudes_name(self):
        with self.claude_places():
            self.sort([['a.txt'], ['a.txt'], None], ['Ask Claude', NOTHING])
        options = self.pick_option.call_args.args[0]
        self.assertIn("Move it to Claude's recommendation: %s/docs/a.txt" % (self.root,), options)
        self.assertFalse(any(option.startswith("Move it to Claude's dir, keeping") for option in options))
        self.assertFalse(any("under Claude's name" in option for option in options))

    def test_a_bracket(self):
        self.assertEqual(inbox._bracket(("your pick", "yours"), 14), "[your pick   ]")
        self.assertEqual(inbox._bracket(("your pick", "yours"), 8), "[yours ]")
        self.assertEqual(inbox._bracket(("your pick", "yours"), 5), "[you]")
        self.assertEqual(inbox._bracket(("x",), 1), " ")

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
            self.sort([['a.txt'], None], ['Describe it'])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(labels, {'a.txt': picker.styled([('a.txt', None), ('  ', None),
                                                          ('[claude: a shopping list]', inbox.CLAUDE_STYLE)]), '': ''})
        self.assertEqual(self.queries[0][:2], (['description'], ai.MODEL))
        # Kept: shown on the next run too, without asking
        with mock.patch('dirdelta.ai._run_query', side_effect=AssertionError('asked again')):
            self.sort([None], [])
        self.assertEqual(self.pick_files.call_args.kwargs['shown_as'](), labels)

    def test_files_being_described_say_so(self):
        sorter = Sort(self.inbox, self.root)
        sorter._describing = {'b.jpg'}
        shown = sorter._shown_as(['a.txt', 'b.jpg'])
        self.assertEqual({relpath: picker.unstyled(text) for relpath, text in shown.items()},
                         {'b.jpg': 'b.jpg  ' + inbox.LOOKING, '': 'Claude: describing 1 file'})
        lines = sorter._previews(['b.jpg'])['b.jpg']
        title = lines.index(picker.styled([(inbox.DESCRIPTION_TITLE, 'bold,magenta')]))
        self.assertEqual(lines[title:title + 2], [picker.styled([(inbox.DESCRIPTION_TITLE, 'bold,magenta')]),
                                        picker.styled([("  Claude is looking at it...", 'grey')])])

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
                      self.pick_option.call_args_list[1].args[0])
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
        menus = [call.args[0] for call in self.pick_option.call_args_list]
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

    def claude_places(self):
        return self.ask_claude({'a.txt': {'description': 'a list', 'action': 'move', 'path': 'docs/a.txt',
                                          'reason': 'a document'},
                                'b.jpg': {'description': 'a cat', 'action': 'move', 'path': 'photos/cats/b.jpg',
                                          'reason': 'a cat photo'},
                                'trip/c.jpg': {'description': 'a beach', 'action': 'move',
                                               'path': 'photos/trips/2024/beach.jpg', 'reason': 'a trip photo'}})

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
        with self.claude_places(), mock.patch('dirdelta.messages.ask', return_value='sunset.jpg') as ask:
            self.sort([['trip/c.jpg'], ['trip/c.jpg'], None],
                      ['Ask Claude', "Move it to Claude's dir, under a name you type", YES])
        self.assertEqual(ask.call_args.args[3], 'beach.jpg')
        self.assertIn('[claude: a beach]', ask.call_args.args[1])
        self.assertTrue(self.exists('sorted', 'photos', 'trips', '2024', 'sunset.jpg'))
        self.assertFalse(self.exists('inbox', 'trip', 'c.jpg'))

    def test_cc_renames_the_selected_file_what_claude_said_going_with_it(self):
        self.sorter = None
        with mock.patch('dirdelta.messages.ask', return_value='list.txt'), mock.patch('dirdelta.dryrun.DRYRUN', False):
            sorter = Sort(self.inbox, self.root)
            sorter._descriptions['a.txt'] = 'a list'
            moved = sorter._rename_selected('a.txt')
        self.assertEqual(moved, {'a.txt': 'list.txt'})
        self.assertTrue(self.exists('inbox', 'list.txt'))
        self.assertEqual(sorter._descriptions, {'list.txt': 'a list'})

    def test_cc_in_the_picker_shows_it_again_on_the_renamed_one(self):
        with mock.patch('dirdelta.messages.ask', return_value='beach'):
            self.sort([picker.Picked(inbox.renaming.PRESSED, 'trip', []), None], [], is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'beach', 'c.jpg'))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'beach')
        self.assertEqual(self.pick_files.call_args.kwargs['twice_keys'], 'c')

    def test_cc_in_the_dir_picker_renames_a_sorted_dir_then_picks_again(self):
        with mock.patch('dirdelta.messages.ask', return_value='documents'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[(inbox.renaming.PRESSED, os.path.join(self.root, 'docs')), os.path.join(self.root, 'documents')])
        self.assertTrue(self.exists('sorted', 'documents', 'old.txt'))
        self.assertTrue(self.exists('sorted', 'documents', 'a.txt'))

    def test_a_typed_name_in_a_picked_dir(self):
        with mock.patch('dirdelta.messages.ask', return_value='list.txt') as ask:
            self.sort([['a.txt'], None], ['Move it to a dir you pick, under a name you type', YES], dirs=[os.path.join(self.root, 'docs')])
        # Without Claude's, its own
        self.assertEqual(ask.call_args.args[3], 'a.txt')
        self.assertTrue(self.exists('sorted', 'docs', 'list.txt'))

    def test_a_typed_name_isnt_a_path_and_is_for_one_file(self):
        with mock.patch('dirdelta.messages.ask', return_value='../x.txt'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick, under a name you type'], dirs=[os.path.join(self.root, 'docs')])
        self.assertEqual(self.show.call_args.args[0], 'Not a name')
        self.assertTrue(self.exists('inbox', 'a.txt'))
        self.sort([['a.txt', 'b.jpg'], None], [NOTHING])
        # A name is typed for one file: not offered for two
        self.assertFalse(any("a name you type" in option for option in self.pick_option.call_args.args[0]))

    def test_ctrl_x_opens_the_selected_one_not_the_picked_ones(self):
        with mock.patch('dirdelta.opening.Opener.open_in_background') as open_in_background:
            self.sort([None], [])
            files = ['a.txt', 'b.jpg', 'trip/c.jpg']
            self.pick_files.call_args.kwargs['on_notify']('\x18', 'trip/c.jpg', ['a.txt', 'b.jpg'])
            self.pick_files.call_args.kwargs['on_notify']('\x18', 'trip/c.jpg', [])
        # The picked ones are opened from the menu's Open
        self.assertEqual(open_in_background.call_args_list, [mock.call(['trip/c.jpg'], files)] * 2)

    def test_what_opening_says_is_on_the_bottom_line(self):
        sorter = Sort(self.inbox, self.root)
        with mock.patch('dirdelta.opening.subprocess.Popen') as popen:
            sorter._opener.open(['trip/c.jpg'], ['trip/c.jpg'])
        self.assertEqual(popen.call_args.args[0], ['xdg-open', os.path.join(self.inbox, 'trip', 'c.jpg')])
        self.assertEqual(sorter._shown_as([])[''], picker.status([('Opened c.jpg', 'yellow')]))

    def test_open_in_the_menu_opens_the_picked_files(self):
        with mock.patch('dirdelta.opening.Opener.open_in_background') as open_in_background:
            self.sort([['a.txt', 'b.jpg'], None], ['Open the 2 files with their programs'])
        open_in_background.assert_called_once_with(['a.txt', 'b.jpg'], ['a.txt', 'b.jpg'])
        # Picked as they were
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['a.txt', 'b.jpg'])

    def test_too_many_to_open_arent_offered_to(self):
        with mock.patch('dirdelta.opening.MAX_OPENED', 2):
            self.sort([['a.txt', 'b.jpg', 'trip/c.jpg'], None], [NOTHING])
        self.assertFalse(any(option.startswith('Open') for option in self.pick_option.call_args.args[0]))

    def test_read_anew_in_the_menu_of_a_drive_inbox_reads_the_selected_folder(self):
        cache = os.path.join(self.tmpdir, 'files.txt')
        with open(cache, 'w') as f:
            f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            for cloud_id, name, parent in (('me', 'me', 'ROOT'), ('in', 'in', 'me'), ('trip', 'trip', 'in'),
                                           ('sorted', 'sorted', 'me')):
                f.write(json.dumps({'id': cloud_id, 'name': name, 'parents': [parent],
                                    'mimeType': 'application/vnd.google-apps.folder'}) + '\n')
            f.write(json.dumps({'id': 'c', 'name': 'c.jpg', 'parents': ['trip'], 'size': '3',
                                'mimeType': 'image/jpeg'}) + '\n')
        picks = [picker.Picked('', 'trip/c.jpg', ['trip/c.jpg']), None]
        with mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', cache), \
                helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as pick_files, \
                helpers.answering_option_picker(['Read cloud/me/in/trip/ anew from Google Drive']) as pick_option, \
                mock.patch('dirdelta.interactive_dir_sync.refresh_replica') as refresh:
            sorter = Sort('cloud/me/in', 'cloud/me/sorted')
            sorter.run()
        # As r does: its folder is the one read (see CloudDirTree.refresh_from_drive())
        refresh.assert_called_once_with(sorter._inbox_tree, 'in/trip/c.jpg')
        options = pick_option.call_args.args[0]
        self.assertEqual(options[-1], 'Read cloud/me/in/trip/ anew from Google Drive')
        # Back to the picker, as it was
        self.assertEqual(pick_files.call_args.kwargs['picked'], ['trip/c.jpg'])
        self.assertEqual(pick_files.call_args.kwargs['selected'], 'trip/c.jpg')

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
        title = lines.index(picker.styled([(inbox.IN_SORTED_TREE_TITLE + " ", 'bold,magenta'), ("Yes", 'bold,green')]))
        self.assertEqual(''.join(line.strip() for line in lines[title + 1:lines.index(inbox.SURELY_A_COPY)]),
                         os.path.join(self.root, 'docs', 'old.txt'))
        self.assertIn(inbox.SURELY_A_COPY, lines)
        # Its hash is kept, for next time
        self.assertIsNotNone(inbox.elsewhere.hashcache.get(os.path.join(self.inbox, 'old.txt'), 'sha1'))

    def test_a_file_the_sorted_tree_hasnt_says_no(self):
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['a.txt'])
        lines = sorter._previews(['a.txt'])['a.txt']
        self.assertTrue(any(line.startswith(picker.styled([(inbox.IN_SORTED_TREE_TITLE + " ", 'bold,magenta'),
                                                           ("No", 'bold,red')])) for line in lines))

    def test_claudes_reason_is_apart_from_the_path(self):
        sorter = Sort(self.inbox, self.root)
        sorter._recommendations['a.txt'] = {'action': 'move', 'path': 'docs/a.txt', 'reason': 'a doc'}
        lines = sorter._previews(['a.txt'])['a.txt']
        title = lines.index(picker.styled([(inbox.DESTINATION_TITLE, 'bold,magenta')]))
        self.assertEqual(lines[title + 1:title + 4], ["  docs/", "", "  a doc"])

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
        self.assertEqual(option, "Remove 1 of the 3 files: copies of files in %s (1 not compared yet: "
                                 "Ctrl-I compares them)" % (self.root,))
        # Offered, as a removal
        self.assertEqual(picker.unstyled(pick_option.call_args.kwargs['shown_as']()[option]).lstrip(), option)
        self.assertEqual(pick_option.call_args.kwargs['shown_as']()[option], ' ' * 9 + picker.styled([(option, 'red')]))

    def test_a_copys_plain_removal_isnt_offered_as_well(self):
        # Removing it from the inbox would do what removing the copy does
        self.copy_in_the_inbox()
        sorter = Sort(self.inbox, self.root)
        sorter._compare(['old.txt'])
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            sorter._act(['old.txt'])
        removals = [option for option in pick_option.call_args.args[0] if option.startswith('Remove')]
        self.assertEqual(removals, ["Remove it: a copy of a file in %s" % (self.root,)])
        # With a file that isn't a copy, both are
        with helpers.answering_option_picker([NOTHING]) as pick_option:
            sorter._act(['old.txt', 'a.txt'])
        removals = [option for option in pick_option.call_args.args[0] if option.startswith('Remove')]
        self.assertEqual(len(removals), 2)

    def test_a_renamed_copy_is_found_by_the_hashes_of_both_with_nothing_compared(self):
        # a.txt's contents, under another name, in the sorted tree
        helpers.make_files(self.root, ['docs/renamed'])
        with open(os.path.join(self.root, 'docs', 'renamed'), 'w') as f:
            f.write('a.txt')
        sorter = Sort(self.inbox, self.root)
        for path in (self.inbox, self.root):
            job = inbox.hashing.job(path)
            self.addCleanup(inbox.hashing._jobs.pop, job.root, None)
            job.scan()
            job._is_started = True
            for relpath in job.files():
                if job._take(relpath):
                    job._hash(relpath)
        self.assertEqual(sorter._copies('a.txt'), ['docs/renamed'])
        self.assertEqual(sorter._checked, {})
        # Marked as hashed in the picker, with how far each got on the bottom line
        shown = sorter._shown_as(['a.txt'])
        self.assertEqual(picker.unstyled(shown['a.txt']), 'a.txt  ' + inbox.hashing.HASHED_TAG)
        self.assertIn('inbox: hashed', shown[''])

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

    def test_the_selected_file_is_compared_in_the_background(self):
        self.sort([None], [])
        on_selection = self.pick_files.call_args.kwargs['on_selection']
        self.assertIs(on_selection.args[4], self.sorter._checked)
        self.assertEqual(on_selection.keywords, {'sends_previews': False})

    def test_claudes_errors_are_said(self):
        with mock.patch('dirdelta.ai._run_query', side_effect=ai.AIError('not logged in')):
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

    def test_files_being_placed_say_so(self):
        sorter = Sort(self.inbox, self.root)
        sorter._placing = {'b.jpg'}
        sorter._descriptions = {'b.jpg': 'a cat'}
        self.assertEqual(sorter._shown_as(['b.jpg'])[''], 'Claude: placing 1 file')
        self.assertEqual(sorter._previews(['b.jpg'])['b.jpg'][-2:],
                         [picker.styled([(inbox.DESTINATION_TITLE, 'bold,magenta')]),
                          picker.styled([("  Claude is working it out...", 'grey')])])

    def test_the_sorted_trees_dirs_for_claude_leave_the_inbox_out(self):
        os.makedirs(os.path.join(self.root, 'unsorted', 'deep'))
        sorter = Sort(os.path.join(self.root, 'unsorted'), self.root)
        self.assertEqual(sorter._root_dirs(), {'': [], 'docs': ['old.txt'], 'photos': ['old.jpg']})

    def test_bad_pairs_are_refused(self):
        with self.assertRaises(inbox.InboxError):
            Sort(self.inbox, os.path.join(self.inbox, 'trip'))
        with self.assertRaises(inbox.InboxError):
            Sort(os.path.join(self.tmpdir, 'nope'), self.root)

    def test_a_new_dir_is_made_in_the_selected_one(self):
        with mock.patch('dirdelta.messages.ask', return_value='2026/taxes/') as ask:
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[('n', os.path.join(self.root, 'docs'))])
        self.assertIn('n', self.pick_under_dir.call_args.kwargs['keys'])
        self.assertEqual(ask.call_args.args[0], "A new dir in %s/docs/" % (self.root,))
        self.assertTrue(self.exists('sorted', 'docs', '2026', 'taxes', 'a.txt'))

    def test_a_new_dirs_name_isnt_a_path_out(self):
        with mock.patch('dirdelta.messages.ask', return_value='../x'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick'], dirs=[('n', self.root)])
        self.assertEqual(self.show.call_args.args[0], "Not a dir's name")
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_the_dirs_moved_to_are_offered_first_next_time(self):
        known = replicas.Replicas()
        with mock.patch('dirdelta.replicas.save') as save:
            # The first time, there are none: straight to the dir picker
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')],
                      known=known)
            self.assertEqual(known.dirs_of(self.root), ['docs'])
            save.assert_called_with(known)
            # Then the recent ones, after picking one (first), a blank line apart
            self.sort([['b.jpg'], None], ['Copy it to a dir you pick', 'Recent: docs/', YES], known=known)
            menu = self.pick_option.call_args_list[1]
            self.assertEqual(menu.args[0], [Sort.PICK_DIR, ' ', 'Recent: docs/'])
            self.assertEqual(menu.kwargs['shown_as'](), {' ': picker.Skipped('')})
            self.assertIn(self.root, menu.kwargs['header'])
            self.assertTrue(self.exists('sorted', 'docs', 'b.jpg'))
            # A new one, or one picked, goes to the top; one not moved to (No) doesn't
            with mock.patch('dirdelta.messages.ask', return_value='new'):
                self.sort([['trip/c.jpg'], None], ['Move it to a dir you pick', 'Pick a dir', YES],
                          dirs=[('n', os.path.join(self.root, 'photos'))], known=known)
                self.sort([['b.jpg'], None], ['Move it to a dir you pick', 'Pick a dir', NO],
                          dirs=[os.path.join(self.root, 'photos')], known=known)
        self.assertEqual(known.dirs_of(self.root), ['photos/new', 'docs'])

    def test_a_dir_in_the_inbox_cant_be_the_destination(self):
        root_with_inbox = self.tmpdir
        sorter = Sort(self.inbox, root_with_inbox)
        with mock.patch('dirdelta.picker.pick_under_dir', return_value=('', os.path.join(self.inbox, 'trip'))):
            self.assertIsNone(sorter._pick_dir('move', '1 file'))
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
                mock.patch.object(Sort, 'run'), mock.patch.object(Sort, 'prepare_hashing'):
            inbox.run(self.inbox, self.root, known)
        self.assertEqual(known.sorts, [(self.inbox, self.root)])
        save.assert_called_once_with(known)

    def test_run_offers_to_hash_the_local_ones_first(self):
        order = []
        with mock.patch('dirdelta.hashes_screen.offer', side_effect=lambda jobs: order.append(
                    sorted(job.root for job in jobs)) or True), \
                mock.patch.object(Sort, 'run', side_effect=lambda: order.append('run')):
            inbox.run(self.inbox, self.root)
        self.assertEqual(order, [sorted([os.path.realpath(self.inbox), os.path.realpath(self.root)]), 'run'])

    def test_nothing_at_the_hashing_question_goes_back_without_sorting(self):
        with mock.patch('dirdelta.hashes_screen.offer', return_value=False), \
                mock.patch.object(Sort, 'run') as run:
            inbox.run(self.inbox, self.root)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
