"""The way picker's keys: asking AI, the tree beside it, exploring a zip, and its menu"""
import contextlib
import os
import unittest
import zipfile
from unittest import mock

import helpers
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from dirdelta.ui import picker
from sync_way_support import Sync, TwoDirsTestCase


class AskAITest(TwoDirsTestCase):
    """Asking the AI, with what it answers scripted"""

    def ask(self, steps, review=None, is_dry_run=False):
        """_ask_ai() of all src's files, the AI answering steps, the review answering review(items)
        (by default, leaving all picked), and every confirmation answered yes (the last option)"""
        def pick_files(root, items, **_):
            self.items = list(items)
            return (review or (lambda items: picker.Picked('', '', list(items))))(items)
        with mock.patch('dirdelta.claude.ai.query.run_query', return_value={'summary': 'ok', 'steps': steps}) as query, \
                mock.patch('dirdelta.ui.picker.pick_files', side_effect=pick_files), \
                mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda options, **_: options[-1]), \
                mock.patch('dirdelta.util.dryrun.DRYRUN', is_dry_run), mock.patch.object(
                    localdiskdirtree.LocalDiskDirTree, 'trashing', return_value=contextlib.nullcontext()):
            self.query = query
            return self.sync._ask_ai(['a.txt', 'b.txt', 'c.txt'])

    def test_what_the_user_approves_is_done(self):
        done = self.ask([{'action': Sync.COPY, 'number': 1, 'reason': 'wanted'},
                         {'action': Sync.RENAME_IN_SRC, 'number': 2, 'path': 'new/b2.txt', 'reason': 'neater'},
                         {'action': Sync.RENAME_IN_DST, 'number': 4, 'path': 'moved/d.txt', 'reason': 'neater'},
                         {'action': Sync.REMOVE, 'number': 3, 'reason': 'junk'}])
        self.assertEqual(sorted(done), ['a.txt', 'b.txt', 'c.txt', 'moved/d.txt'])
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'a.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.src_path, 'new/b2.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'moved/d.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.src_path, 'c.txt')))
        self.assertIsNone(self.sync._last_action)

    def test_whats_unpicked_in_the_review_isnt_done(self):
        steps = [{'action': Sync.COPY, 'number': 1, 'reason': ''}, {'action': Sync.COPY, 'number': 2, 'reason': ''}]
        done = self.ask(steps, lambda items: picker.Picked('', '', ['Copy to destination/b.txt']))
        self.assertEqual(done, ['b.txt'])
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'a.txt')))

    def test_quitting_the_review_does_nothing(self):
        self.assertIsNone(self.ask([{'action': Sync.COPY, 'number': 1, 'reason': ''}], lambda items: None))
        self.assertEqual(sorted(os.listdir(self.dst_path)), ['old'])

    def test_a_dry_run_changes_nothing(self):
        done = self.ask([{'action': Sync.COPY, 'number': 1, 'reason': ''},
                         {'action': Sync.REMOVE, 'number': 2, 'reason': ''}], is_dry_run=True)
        self.assertEqual(sorted(done), ['a.txt', 'b.txt'])
        self.assertEqual(sorted(os.listdir(self.dst_path)), ['old'])
        self.assertTrue(os.path.exists(os.path.join(self.src_path, 'b.txt')))

    def test_a_target_thats_taken_isnt_offered(self):
        self.ask([{'action': Sync.RENAME_IN_SRC, 'number': 1, 'path': 'b.txt', 'reason': ''},
                  {'action': Sync.COPY, 'number': 3, 'reason': ''}])
        self.assertEqual(self.items, ['Copy to destination/c.txt'])

    def test_it_may_read_the_files_of_its_focus(self):
        with mock.patch('dirdelta.claude.ai.query.run_query', return_value={'summary': '', 'answer': 'It says hi', 'steps': []}) as query, \
                mock.patch('dirdelta.ui.messages.show') as show:
            self.assertIsNone(self.sync._ask_ai(['a.txt', 'b.txt'], ['b.txt']))
        prompt, readable_dirs = query.call_args.args[:2]
        self.assertEqual(readable_dirs, [self.src_path])
        self.assertIn("read it at %s" % (os.path.join(self.src_path, 'b.txt'),), prompt)
        self.assertNotIn(os.path.join(self.src_path, 'a.txt'), prompt)
        self.assertEqual(show.call_args.args[:2], ('The AI says', ['It says hi']))

    def test_the_key_with_nothing_picked_asks_about_all_the_files(self):
        with mock.patch.object(Sync, '_ask_ai', return_value=None) as ask, helpers.scripted_files_picker(
                mock.Mock(side_effect=[picker.Picked('a', '', []), None])), \
                mock.patch('dirdelta.screens.hashes_screen.jobs_of', return_value=[]):
            self.sync.browse()
        ask.assert_called_once_with(['a.txt', 'b.txt', 'c.txt'], [])

    def test_the_key_asks_about_the_picked_ones(self):
        with mock.patch.object(Sync, '_ask_ai', return_value=None) as ask, helpers.scripted_files_picker(
                mock.Mock(side_effect=[picker.Picked('a', '', ['b.txt']), None])), \
                mock.patch('dirdelta.screens.hashes_screen.jobs_of', return_value=[]):
            self.sync.browse()
        ask.assert_called_once_with(['b.txt'], ['b.txt'])


class ActInDstTest(TwoDirsTestCase):
    """Enter in the tree beside the picker, dst's"""

    def setUp(self):
        super().setUp()
        helpers.make_files(self.dst_path, ['repo/x.txt', 'repo/y.txt', 'meta/hashes.sqlite'])

    def enter(self, side_selected, confirmations=('Yes', 'Yes, remove them'), is_dry_run=False):
        """browse(), Enter in the side tree at side_selected, then choosing to remove it, confirming
        with confirmations"""
        answers = iter(confirmations)

        def pick_option(options, **kwargs):
            if options[-1].startswith('Remove'):
                self.options, self.shown = options, kwargs['shown_as']()
                return options[-1]
            return next(answers)
        picks = iter([picker.Picked(picker.SIDE_KEY, 'a.txt', [], side_selected), None])
        with helpers.scripted_files_picker(lambda relpaths: next(picks)) as pick_files, \
                mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.screens.hashes_screen.jobs_of', return_value=[]), \
                mock.patch('dirdelta.util.dryrun.DRYRUN', is_dry_run):
            self.sync.browse()
        return pick_files

    def test_a_dir_is_removed_and_the_replicas_diffed_anew(self):
        self.enter('repo')
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'repo', 'y.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'old', 'd.txt')))
        self.assertTrue(self.sync.has_changed)

    def test_src_lacks_nothing_more_after_removing_from_dst_of_what_it_has(self):
        helpers.make_files(self.src_path, ['repo/x.txt'])
        pick_files = self.enter('repo')
        # dst had src's repo/x.txt: now it's what dst lacks
        self.assertIn('repo/x.txt', pick_files.call_args.args[1])

    def test_it_says_where_it_removes_from_and_asks_twice(self):
        self.enter('repo', ('No',))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))
        self.assertFalse(self.sync.has_changed)

    def test_a_dry_run_changes_nothing(self):
        self.enter('repo', is_dry_run=True)
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))
        self.assertFalse(self.sync.has_changed)

    def test_d_there_goes_straight_to_confirming(self):
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=['Yes', 'Yes, remove them']) as pick_option, \
                mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.sync._act_in_dst('repo', True)
        self.assertTrue(helpers.labels_of(pick_option.call_args_list[0].args[0])[-1] == 'Yes')
        self.assertFalse(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))

    def test_d_on_a_read_only_one_says_so(self):
        with mock.patch('dirdelta.sync.replica_ops.is_writable', return_value=False), \
                mock.patch('dirdelta.ui.picker.pick_option') as pick_option:
            self.assertIsNone(self.sync._act_in_dst('repo', True))
        pick_option.assert_not_called()
        self.assertEqual(messages.show.call_args.args[0], "Can't remove it")

    def test_not_all_of_dst(self):
        self.enter('')
        self.assertEqual(messages.show.call_args.args[0], "That's all of %s" % (self.dst_path,))
        self.assertTrue(os.path.exists(os.path.join(self.dst_path, 'repo', 'x.txt')))

    def test_a_read_only_one_cant(self):
        with mock.patch('dirdelta.sync.replica_ops.is_writable', return_value=False):
            self.enter('repo', ('No',))
        self.assertIsInstance(self.shown[self.options[-1]], picker.Disabled)


class ExploreTest(TwoDirsTestCase):
    """e and the menus' Explore, on a zip"""

    def setUp(self):
        super().setUp()
        self.zip_path = os.path.join(self.src_path, 'z.zip')
        with zipfile.ZipFile(self.zip_path, 'w') as archive:
            archive.writestr('in/side.txt', 'hello')

    def browse(self, picks):
        results = iter(picks + [None])
        with helpers.scripted_files_picker(lambda relpaths: next(results)), \
                mock.patch('dirdelta.screens.hashes_screen.jobs_of', return_value=[]), \
                mock.patch('dirdelta.ui.picker.view_files') as view:
            self.sync.browse()
        return view

    def test_the_key_shows_whats_in_it(self):
        view = self.browse([picker.Picked('e', 'z.zip', [])])
        self.assertEqual(view.call_args.args[:2], ('z.zip', ['in/side.txt']))

    def test_the_menu_offers_it_on_a_zip_only(self):
        with mock.patch('dirdelta.ui.picker.view_files') as view, helpers.answering_option_picker(['Explore']) as options:
            self.sync._act(['z.zip'])
        self.assertTrue(any(option.startswith('Explore') for option in helpers.labels_of(options.call_args.args[0])))
        self.assertEqual(view.call_args.args[1], ['in/side.txt'])
        with helpers.answering_option_picker([None]) as options:
            self.sync._act(['a.txt'])
        self.assertFalse(any(option.startswith('Explore') for option in helpers.labels_of(options.call_args.args[0])))


class ContextMenuTest(TwoDirsTestCase):
    """: in the sync's picker"""

    def press(self, picks, answer):
        """browse(), ':' being pressed on the Picked of picks, then quitting; the menu answering answer
        (what its options start with). The options are self.options."""
        def pick_option(options, **kwargs):
            self.options = helpers.labels_of(options)
            self.shown = helpers.shown_of(options)
            return helpers.answer_of(options, answer)
        results = iter(picks + [None])
        with helpers.scripted_files_picker(lambda relpaths: next(results)) as pick_files, mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.screens.hashes_screen.jobs_of', return_value=[]):
            self.sync.browse()
        return pick_files

    def test_its_options_are_whats_there_with_their_keys(self):
        self.press([picker.Picked(':', 'a.txt', [])], 'Nothing')
        shown = [picker.unstyled(self.shown[option]) for option in self.options
                 if not isinstance(self.shown[option], picker.Skipped)]
        self.assertTrue(any(line.startswith('[Space]') and 'Pick a.txt' in line for line in shown))
        self.assertTrue(any(line.startswith('[a]') for line in shown))
        self.assertTrue(any(line.startswith('[Ctrl-X]') for line in shown))
        self.assertTrue(any(line.startswith('[cc]') for line in shown))
        self.assertTrue(any(line.startswith('[#]') for line in shown))
        # What only the picker does is shown, and can't be chosen
        self.assertTrue(any(isinstance(self.shown[option], picker.Skipped) and 'search' in self.shown[option].text
                            for option in self.options))

    def test_on_the_root_theres_nothing_to_open_or_rename(self):
        self.press([picker.Picked(':', '', [])], 'Nothing')
        self.assertFalse(any(option.startswith(('Open', 'Rename')) for option in self.options))

    def test_ask_ai_is_about_all_the_files(self):
        with mock.patch.object(Sync, '_ask_ai', return_value=None) as ask:
            self.press([picker.Picked(':', 'a.txt', [])], 'Ask AI')
        ask.assert_called_once_with(['a.txt', 'b.txt', 'c.txt'], ['a.txt'])

    def test_pick_comes_back_picked(self):
        pick_files = self.press([picker.Picked(':', 'b.txt', [])], 'Pick')
        self.assertEqual(pick_files.call_args.kwargs['picked'], ['b.txt'])

    def test_what_to_do_is_enters_menu_of_the_selected_one(self):
        with mock.patch.object(Sync, '_act', return_value=None) as act:
            self.press([picker.Picked(':', 'b.txt', [])], 'Choose what to do')
        act.assert_called_once_with(['b.txt'], 'b.txt')

    def test_open_opens_the_selected_one(self):
        with mock.patch('dirdelta.ui.opening.Opener.press') as press:
            self.press([picker.Picked(':', 'b.txt', [])], 'Open')
        self.assertEqual(press.call_args.args[0], ['b.txt'])


if __name__ == '__main__':
    unittest.main()
