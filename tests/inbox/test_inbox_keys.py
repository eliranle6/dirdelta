"""The inbox picker's keys and menus: asking AI, exploring, opening, reading anew"""
import json
import os
import unittest
import zipfile
from unittest import mock

import helpers
from dirdelta.inbox import formatting
from dirdelta.ui import picker
from inbox_support import InboxSortTest, NOTHING, Sort, YES


class KeysTest(InboxSortTest):
    """Keys and menus"""

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

    def test_a_bracket(self):
        self.assertEqual(formatting.bracket(("your pick", "yours"), 14), "[your pick   ]")
        self.assertEqual(formatting.bracket(("your pick", "yours"), 8), "[yours ]")
        self.assertEqual(formatting.bracket(("your pick", "yours"), 5), "[you]")
        self.assertEqual(formatting.bracket(("x",), 1), " ")

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
        with mock.patch('dirdelta.ui.opening.names.MAX_OPENED', 2):
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
        with mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', cache), \
                helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as pick_files, \
                helpers.answering_option_picker(['Read cloud/me/in/trip/ anew from Google Drive']) as pick_option, \
                mock.patch('dirdelta.sync.replica_ops.refresh_replica') as refresh:
            sorter = Sort('cloud/me/in', 'cloud/me/sorted')
            sorter.run()
        # As r does: its folder is the one read (see CloudDirTree.refresh_from_drive())
        refresh.assert_called_once_with(sorter._inbox_tree, 'trip/c.jpg')
        options = helpers.labels_of(pick_option.call_args.args[0])
        self.assertEqual(options[-1], 'Read cloud/me/in/trip/ anew from Google Drive')
        # Back to the picker, as it was
        self.assertEqual(pick_files.call_args.kwargs['picked'], ['trip/c.jpg'])
        self.assertEqual(pick_files.call_args.kwargs['selected'], 'trip/c.jpg')


if __name__ == '__main__':
    unittest.main()
