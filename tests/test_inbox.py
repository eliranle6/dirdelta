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
from dirdelta.claude import ai
from dirdelta.drive import clouddirtree
from dirdelta.inbox import inbox
from dirdelta.ui import picker
from dirdelta.known import replicalog
from dirdelta.known import replicas

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
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'),
                        mock.patch('dirdelta.ui.messages.print_progress'),
                        mock.patch('dirdelta.ui.messages.show'),
                        mock.patch('dirdelta.claude.ai.CACHE_FILE', os.path.join(self.tmpdir, 'ai.json'))):
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
                mock.patch('dirdelta.ui.picker.pick_under_dir',
                           side_effect=lambda *_, **__: self.picked_dir(dirs.pop(0))) as self.pick_under_dir, \
                mock.patch('dirdelta.ui.picker.view_files', return_value=view) as self.view_files, \
                mock.patch('dirdelta.util.dryrun.DRYRUN', is_dry_run), self.synchronously():
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
        with mock.patch('dirdelta.ui.messages.progress_screen', wraps=inbox.messages.progress_screen) as screen:
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
        menu = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertIn('Remove it: it looks like junk (to the trash)', menu)

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
                helpers.answering_option_picker(['Move it to a dir you pick', YES, 'Add it to its', replicalog.NO_ENTRY]) as pick, \
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

    def test_remove_is_asked_twice(self):
        self.sort([['a.txt'], None], ['Remove it from', YES, SURE])
        self.assertFalse(self.exists('inbox', 'a.txt'))
        self.assertEqual(helpers.labels_of(self.pick_option.call_args.args[0]), [NO, SURE])
        self.sort([['b.jpg'], None], ['Remove it from', YES, NO])
        self.assertTrue(self.exists('inbox', 'b.jpg'))

    def test_a_removal_waits_for_enter_and_says_if_some_werent_removed(self):
        with mock.patch('dirdelta.ui.messages.progress_screen', wraps=inbox.messages.progress_screen) as screen:
            self.sort([['a.txt'], None], ['Remove it from', YES, SURE])
        # "Press Enter to continue" once it's done
        self.assertNotIn('wait', screen.call_args.kwargs)
        self.show.assert_not_called()
        real_unlink = os.unlink

        def unlink(path):
            if path.endswith('b.jpg'):
                raise PermissionError('read-only')
            real_unlink(path)
        with mock.patch('dirdelta.trees.localdiskdirtree.os.unlink', side_effect=unlink):
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
        with mock.patch('dirdelta.claude.ai._run_query', return_value={'summary': 'ok', 'steps': steps}), \
                mock.patch('dirdelta.ui.messages.ask', return_value='sort them'), \
                mock.patch('dirdelta.ui.picker.pick_files', side_effect=pick_files), \
                helpers.answering_option_picker(answers), mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.LocalReplica.trashing', return_value=contextlib.nullcontext()), \
                mock.patch('dirdelta.ui.picker.view_files') as self.view_files:
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

    def test_the_context_menu_with_nothing_picked(self):
        self.sort([picker.Picked(':', 'a.txt', []), None], [NOTHING])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        for start in ("Choose what to do with a.txt", "Pick a.txt", "Ask AI", "Have Claude describe a.txt",
                      "Open a.txt", "Rename a.txt", "Replicas dashboard"):
            self.assertTrue(any(option.startswith(start) for option in options), start)

    def test_the_context_menu_goes_to_enters_menu_of_the_selected_one(self):
        with mock.patch.object(Sort, '_act', return_value=None) as act:
            self.sort([picker.Picked(':', 'trip', []), None], ["Choose what to do"])
        act.assert_called_once_with(['trip/c.jpg'], 'trip')

    def test_with_files_picked_the_key_is_enters_menu(self):
        with mock.patch.object(Sort, '_act', return_value=None) as act:
            self.sort([picker.Picked(':', 'a.txt', ['b.jpg']), None], [])
        act.assert_called_once_with(['b.jpg'], 'a.txt')

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

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_what_cant_be_read_is_said_once_at_the_start(self):
        locked = os.path.join(self.inbox, 'locked')
        os.makedirs(locked)
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        self.sort([['a.txt'], ['a.txt'], None], [NOTHING, NOTHING])
        warnings = [call for call in self.show.call_args_list if call.args[0] == "Warning: couldn't read everything"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("(1 error), so its list lacks what's there", warnings[0].args[1][0])

    def refreshed(self, pick):
        """How many times the side tree's listed in a sort with pick, then quitting, and the picks after pick"""
        sorter = Sort(self.inbox, self.root)
        with mock.patch('dirdelta.ui.sidetree._listed', wraps=inbox.sidetree._listed) as listed, \
                mock.patch('dirdelta.ui.picker.pick_files', side_effect=[pick, None]) as pick_files, \
                mock.patch('dirdelta.sync.interactive_dir_sync.refresh_replica') as self.refresh_replica:
            sorter.run()
        return listed.call_count, pick_files.call_args_list[-1].kwargs['picked']

    def test_ctrl_r_lists_the_side_tree_anew(self):
        self.assertEqual(self.refreshed(picker.Picked(Sort.REFRESH_KEY, 'a.txt', ['a.txt'])), (2, ['a.txt']))
        self.refresh_replica.assert_not_called()

    def test_ctrl_r_in_the_side_tree_lists_it_anew_and_moves_nothing(self):
        count, picked = self.refreshed(picker.Picked(picker.SIDE_KEY, 'a.txt', ['a.txt'], 'docs', Sort.REFRESH_KEY))
        self.assertEqual((count, picked), (2, ['a.txt']))
        self.assertTrue(os.path.exists(os.path.join(self.inbox, 'a.txt')))
        self.refresh_replica.assert_not_called()

    def test_ctrl_r_in_the_side_tree_stays_there_but_a_move_from_it_doesnt(self):
        sorter = Sort(self.inbox, self.root)
        picks = [picker.Picked(picker.SIDE_KEY, 'a.txt', ['a.txt'], 'docs', Sort.REFRESH_KEY),
                 picker.Picked(picker.SIDE_KEY, 'a.txt', ['a.txt'], 'docs'), None]
        with mock.patch('dirdelta.ui.picker.pick_files', side_effect=picks) as pick_files, \
                mock.patch.object(Sort, '_move_to_side', return_value=None):
            sorter.run()
        self.assertEqual([call.kwargs['side'].start for call in pick_files.call_args_list], [None, 'docs', None])

    def test_ctrl_r_with_the_selected_file_gone_selects_the_closest(self):
        answers = [picker.Picked(Sort.REFRESH_KEY, 'a.txt', []), None]

        def pick(root, files, **kwargs):
            answer = answers.pop(0)
            if answer is not None:
                os.remove(os.path.join(self.inbox, 'a.txt'))
            return answer
        with mock.patch('dirdelta.ui.picker.pick_files', side_effect=pick) as pick_files:
            Sort(self.inbox, self.root).run()
        self.assertEqual(pick_files.call_args.kwargs['selected'], 'b.jpg')

    def drive_inbox(self):
        """A sort whose inbox is on Drive as far as _ai_files() can tell, with a.txt, b.jpg and trip/c.jpg"""
        sorter = Sort(self.inbox, self.root)
        sorter.inbox_is_cloud = True
        sorter._inbox_tree = mock.MagicMock()
        sorter._inbox_tree.__contains__.side_effect = lambda relpath: relpath in ('a.txt', 'b.jpg', 'trip/c.jpg')
        sorter._inbox_tree.file_size.return_value = 1
        sorter._inbox_tree.cant_fetch.return_value = None
        return sorter

    def test_a_file_gone_during_a_batch_is_left_out_and_not_called_failed(self):
        sorter = self.drive_inbox()
        with mock.patch.object(sorter, '_downloaded', return_value='/tmp/x'), \
                mock.patch('dirdelta.claude.ai.describe', return_value={'a.txt': 'a note'}):
            sorter._describe(['a.txt', 'gone.txt'])
        self.assertEqual(sorter._descriptions, {'a.txt': 'a note'})
        self.assertEqual(sorter._failed, {})

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

    def read_only_inbox(self):
        patcher = mock.patch('dirdelta.sync.interactive_dir_sync.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.inbox))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_from_a_read_only_inbox_only_copying_is_left_and_its_said(self):
        self.read_only_inbox()
        self.sort([['a.txt'], None], [NOTHING])
        self.assertEqual(self.show.call_args_list[0].args[0], 'Read-only')
        self.assertIn('you can still copy', self.show.call_args_list[0].args[1][0])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertTrue(any(option.startswith('Copy it') for option in options))
        self.assertFalse(any(option.startswith(('Move', 'Remove')) for option in options))

    def read_only_root(self):
        patcher = mock.patch('dirdelta.sync.interactive_dir_sync.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

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
        with mock.patch('dirdelta.sync.interactive_dir_sync.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.inbox)):
            self.assertEqual(names(), [Sort.COPY_TO])
        with mock.patch('dirdelta.sync.interactive_dir_sync.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.root)):
            self.assertEqual(names(), [Sort.MOVE_IN_INBOX, Sort.REMOVE])

    def test_with_both_read_only_the_ai_isnt_asked(self):
        sorter = Sort(self.inbox, self.root)
        with mock.patch('dirdelta.sync.interactive_dir_sync.is_writable', return_value=False), \
                mock.patch('dirdelta.screens.aiplan_screen.ask') as ask:
            self.assertIsNone(sorter._ask_ai(['a.txt']))
        ask.assert_not_called()

    def test_a_copy_from_a_read_only_inbox_goes_through(self):
        self.read_only_inbox()
        self.sort([['a.txt'], None], ['Copy it to a dir you pick', YES], dirs=[os.path.join(self.root, 'docs')], is_dry_run=False)
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))
        self.assertTrue(self.exists('inbox', 'a.txt'))

    def test_the_menu_starts_with_nothing(self):
        self.sort([['a.txt'], None], [NOTHING])
        # Each kind of action apart, after a blank line (skipped when moving)
        with_blanks = [picker.option_label(option) for option in self.pick_option.call_args.args[0]]
        self.assertEqual([option.split(' ')[0] for option in with_blanks],
                         ['Nothing:', '', 'Ask', 'Describe', 'Ask', '', 'Move', 'Move', 'Move', '', 'Copy', '', 'Remove', '', 'Open'])
        options = [option for option in with_blanks if option]
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
        # And below the menu, what it does and where to
        line = self.pick_option.call_args.kwargs['previews_below'][Sort.MOVE_TO][0]
        self.assertIn(" MOVE ", line)
        self.assertIn(self.root + '/', line)

    def test_claudes_dir_under_the_files_own_name_isnt_offered_when_its_claudes_name(self):
        with self.claude_places():
            self.sort([['a.txt'], ['a.txt'], None], ['Ask Claude', NOTHING])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
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
        return mock.patch('dirdelta.claude.ai._run_query', side_effect=run_query)

    def test_descriptions_are_shown_after_the_names(self):
        with self.ask_claude({'a.txt': {'description': 'a shopping list'}}):
            # Described in the background; quitting waits for it
            self.sort([['a.txt'], None], ['Describe it'])
        labels = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(labels, {'a.txt': picker.styled([('a.txt', None), ('  ', None),
                                                          ('[claude: a shopping list]', inbox.CLAUDE_STYLE)]), '': ''})
        self.assertEqual(self.queries[0][:2], (['description'], ai.MODEL))
        # Kept: shown on the next run too, without asking
        with mock.patch('dirdelta.claude.ai._run_query', side_effect=AssertionError('asked again')):
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
        with self.claude_places(), mock.patch('dirdelta.ui.messages.ask', return_value='sunset.jpg') as ask:
            self.sort([['trip/c.jpg'], ['trip/c.jpg'], None],
                      ['Ask Claude', "Move it to Claude's dir, under a name you type", YES])
        self.assertEqual(ask.call_args.args[3], 'beach.jpg')
        self.assertIn('[claude: a beach]', ask.call_args.args[1])
        self.assertTrue(self.exists('sorted', 'photos', 'trips', '2024', 'sunset.jpg'))
        self.assertFalse(self.exists('inbox', 'trip', 'c.jpg'))

    def test_cc_renames_the_selected_file_what_claude_said_going_with_it(self):
        self.sorter = None
        with mock.patch('dirdelta.ui.messages.ask', return_value='list.txt'), mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            sorter = Sort(self.inbox, self.root)
            sorter._descriptions['a.txt'] = 'a list'
            moved = sorter._rename_selected('a.txt')
        self.assertEqual(moved, {'a.txt': 'list.txt'})
        self.assertTrue(self.exists('inbox', 'list.txt'))
        self.assertEqual(sorter._descriptions, {'list.txt': 'a list'})

    def test_cc_in_the_picker_shows_it_again_on_the_renamed_one(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='beach'):
            self.sort([picker.Picked(inbox.renaming.PRESSED, 'trip', []), None], [], is_dry_run=False)
        self.assertTrue(self.exists('inbox', 'beach', 'c.jpg'))
        self.assertEqual(self.pick_files.call_args.kwargs['selected'], 'beach')
        self.assertEqual(self.pick_files.call_args.kwargs['twice_keys'], 'c')

    def test_cc_in_the_dir_picker_renames_a_sorted_dir_then_picks_again(self):
        with mock.patch('dirdelta.ui.messages.ask', return_value='documents'):
            self.sort([['a.txt'], None], ['Move it to a dir you pick', YES],
                      dirs=[(inbox.renaming.PRESSED, os.path.join(self.root, 'docs')), os.path.join(self.root, 'documents')])
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

    def test_ctrl_x_opens_the_selected_one_not_the_picked_ones(self):
        with mock.patch('dirdelta.ui.opening.Opener.open_in_background') as open_in_background:
            self.sort([None], [])
            files = ['a.txt', 'b.jpg', 'trip/c.jpg']
            self.pick_files.call_args.kwargs['on_notify']('\x18', 'trip/c.jpg', ['a.txt', 'b.jpg'])
            self.pick_files.call_args.kwargs['on_notify']('\x18', 'trip/c.jpg', [])
        # The picked ones are opened from the menu's Open
        self.assertEqual(open_in_background.call_args_list, [mock.call(['trip/c.jpg'], files)] * 2)

    def test_open_in_the_menu_opens_the_picked_files(self):
        with mock.patch('dirdelta.ui.opening.Opener.open_in_background') as open_in_background:
            self.sort([['a.txt', 'b.jpg'], None], ['Open the 2 files with their programs'])
        open_in_background.assert_called_once_with(['a.txt', 'b.jpg'], ['a.txt', 'b.jpg'])
        # Picked as they were
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['a.txt', 'b.jpg'])

    def test_too_many_to_open_arent_offered_to(self):
        with mock.patch('dirdelta.ui.opening.MAX_OPENED', 2):
            self.sort([['a.txt', 'b.jpg', 'trip/c.jpg'], None], [NOTHING])
        self.assertFalse(any(option.startswith('Open') for option in helpers.labels_of(self.pick_option.call_args.args[0])))

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
        with mock.patch('dirdelta.drive.drivecache.LINES_FILE', cache), \
                helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as pick_files, \
                helpers.answering_option_picker(['Read cloud/me/in/trip/ anew from Google Drive']) as pick_option, \
                mock.patch('dirdelta.sync.interactive_dir_sync.refresh_replica') as refresh:
            sorter = Sort('cloud/me/in', 'cloud/me/sorted')
            sorter.run()
        # As r does: its folder is the one read (see CloudDirTree.refresh_from_drive())
        refresh.assert_called_once_with(sorter._inbox_tree, 'trip/c.jpg')
        options = helpers.labels_of(pick_option.call_args.args[0])
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
        with mock.patch('dirdelta.inbox.inbox.PREVIEWS_INTERVAL', 0), self.assertRaises(picker.PickerClosed):
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

    def test_claudes_errors_are_said(self):
        with mock.patch('dirdelta.claude.ai._run_query', side_effect=ai.AIError('not logged in')):
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

    def test_bad_pairs_are_refused(self):
        with self.assertRaises(inbox.InboxError):
            Sort(self.inbox, os.path.join(self.inbox, 'trip'))
        with self.assertRaises(inbox.InboxError):
            Sort(os.path.join(self.tmpdir, 'nope'), self.root)

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

    def two_trees(self):
        """The sort with a tree each (as a local inbox and a Drive sorted tree have), both local
        here, so the copy-then-remove path is run without Drive"""
        sorter = Sort(self.inbox, self.root)
        sorter.is_same_kind = False
        return sorter

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
                mock.patch('dirdelta.trees.localdiskdirtree.shutil.copy2', side_effect=copy):
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
        with mock.patch('dirdelta.drive.drivecache.LINES_FILE', cache):
            sorter = Sort(self.inbox, 'cloud/me')
            with self.assertRaises(inbox.drivecache.DriveCacheError):
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


    # A dir as a whole

    def claude_on_dirs(self, dir_answer, description='a beach at sunset'):
        """Patch Claude: files described as description, a dir answered dir_answer; its calls are
        the mock's"""
        def query(prompt, readable_dirs, schema, max_turns, model, system_prompt=ai.SYSTEM_PROMPT):
            if system_prompt == ai.DIR_SYSTEM_PROMPT:
                return dir_answer
            return {'files': [{'number': number, 'description': description}
                              for number in range(1, prompt.count('size ') + 1)]}
        return mock.patch('dirdelta.claude.ai._run_query', side_effect=query)

    def cache_dir_recommendation(self, dirpath, recommendation):
        """Put what Claude said of the inbox's dir in its cache, as asked before"""
        sorter = Sort(self.inbox, self.root)
        files = sorter._inbox_files()
        key = sorter._dir_key(dirpath, *sorter._dir_stats(files)[dirpath])
        with open(ai.CACHE_FILE, 'w') as f:
            json.dump({key: {'recommendations': {sorter.root_path: recommendation}}}, f)

    def test_ctrl_i_on_a_dir_asks_about_it_as_a_whole(self):
        helpers.make_files(self.inbox, ['trip/d.jpg', 'trip/day2/e.jpg'])
        sorter = Sort(self.inbox, self.root)
        files = sorter._inbox_files()
        answer = {'action': 'move', 'path': '/photos/2024/rome trip/', 'summary': 'Rome trip photos.',
                  'reason': 'one trip'}
        with self.claude_on_dirs(answer) as query:
            sorter._on_key(inbox.DESCRIBE_KEY, 'trip', [], files)
            sorter.wait_for_claude()
        self.assertEqual(sorter._dir_recommendation('trip'),
                         {'action': 'move', 'path': 'photos/2024/rome trip', 'summary': 'Rome trip photos',
                          'reason': 'one trip'})
        # Its files described first (all three: no more than DIR_FILES_DESCRIBED), not asked where each goes
        self.assertEqual(sorter._descriptions, {relpath: 'a beach at sunset' for relpath in
                                                ['trip/c.jpg', 'trip/d.jpg', 'trip/day2/e.jpg']})
        self.assertEqual(sorter._recommendations, {})
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
        self.assertEqual(again._dir_recommendation('trip')['path'], 'photos/2024/rome trip')
        # Picked files, or the root: each file, as before
        with mock.patch.object(Sort, 'ask_in_background') as ask:
            sorter._on_key(inbox.DESCRIBE_KEY, 'trip', ['trip/c.jpg'], files)
            sorter._on_key(inbox.DESCRIBE_KEY, '', [], files)
        self.assertEqual([call.args[0] for call in ask.call_args_list], [['trip/c.jpg'], files])

    def test_a_dir_that_changed_is_asked_about_anew(self):
        self.cache_dir_recommendation('trip', {'action': 'split', 'path': '', 'summary': 'mixed', 'reason': 'r'})
        sorter = Sort(self.inbox, self.root)
        sorter._load_cached(sorter._inbox_files())
        self.assertEqual(sorter._dir_recommendation('trip')['action'], 'split')
        preview = '\n'.join(picker.unstyled(line) for line in sorter._previews(sorter._inbox_files())['trip'])
        self.assertIn("Its files don't go together", preview)
        helpers.make_files(self.inbox, ['trip/new.jpg'])
        sorter._load_cached(sorter._inbox_files())
        self.assertIsNone(sorter._dir_recommendation('trip'))
        preview = '\n'.join(picker.unstyled(line) for line in sorter._previews(sorter._inbox_files())['trip'])
        self.assertIn("Ctrl-I asks Claude about the dir", preview)

    def test_claude_failing_on_a_dir_says_so(self):
        sorter = Sort(self.inbox, self.root)
        files = sorter._inbox_files()
        with self.claude_on_dirs({'action': 'move', 'path': '..', 'summary': 's', 'reason': 'r'}):
            sorter._on_key(inbox.DESCRIBE_KEY, 'trip', [], files)
            sorter.wait_for_claude()
        self.assertIsNone(sorter._dir_recommendation('trip'))
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
        self.assertEqual(inbox._spread([1, 2, 3], 5), [1, 2, 3])
        self.assertEqual(inbox._spread(list(range(10)), 4), [0, 3, 6, 9])
        self.assertEqual(inbox._spread(list(range(10)), 1), [0])


if __name__ == '__main__':
    unittest.main()
