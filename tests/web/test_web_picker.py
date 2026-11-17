"""dirdelta's pickers done in the browser (web/picker/): the same picker calls, the browser's answers"""
import os
import tempfile
import shutil
import unittest

import helpers
from dirdelta.ui import picker
from web_support import WebTest


class MenuTest(WebTest):
    def test_the_option_chosen_is_returned(self):
        screen = self.start(lambda: picker.pick_option(['Copy', picker.Option('rm', 'Remove'), picker.BLANK, 'Quit']))
        screen.select('Remove')
        screen.enter()
        self.assertEqual('rm', self.result())

    def test_a_greyed_out_option_cant_be_chosen(self):
        screen = self.start(lambda: picker.pick_option(['Copy', 'Remove'], shown_as=lambda: {'Remove': picker.Disabled('Remove: nothing')}))
        self.wait_until(lambda: screen.items.info['Remove'].get('d'))
        screen.select('Remove')
        screen.enter()
        screen.select('Copy')
        screen.enter()
        self.assertEqual('Copy', self.result())

    def test_an_option_it_hasnt_cant_be_chosen(self):
        screen = self.start(lambda: picker.pick_option(['Copy', 'Quit']))
        screen.select('Remove everything')
        screen.enter()
        self.assertEqual('Copy', self.result())

    def test_quitting_returns_none(self):
        screen = self.start(lambda: picker.pick_option(['Copy']))
        screen.quit()
        self.assertIsNone(self.result())

    def test_the_options_texts_and_the_status_come_in_as_they_change(self):
        counts = {'n': 1}
        screen = self.start(lambda: picker.pick_option(['Copy'], shown_as=lambda: {'Copy': 'Copy %d files' % counts['n'], '': 'working'}))
        self.wait_until(lambda: screen.items.info['Copy'].get('x') == 'Copy 1 files')
        counts['n'] = 5
        self.wait_until(lambda: screen.items.info['Copy'].get('x') == 'Copy 5 files')
        self.assertEqual('working', screen.items.status)
        screen.quit()
        self.result()


class FilesTest(WebTest):
    FILES = ['a/x.txt', 'a/y.txt', 'b.txt']

    def test_picking_a_dir_picks_its_files(self):
        screen = self.start(lambda: picker.pick_files('/r', self.FILES))
        screen.pick(['a'], True)
        screen.enter()
        self.assertEqual(['a/x.txt', 'a/y.txt'], self.result().files)

    def test_enter_with_nothing_picked_does_nothing_unless_it_picks_the_selection(self):
        screen = self.start(lambda: picker.pick_files('/r', self.FILES))
        screen.select('b.txt')
        screen.enter()
        self.assertFalse(screen._done.is_set())
        screen.quit()
        self.assertIsNone(self.result())
        screen = self.start(lambda: picker.pick_files('/r', self.FILES, enter_picks_selection=True))
        screen.select('b.txt')
        screen.enter()
        self.assertEqual(['b.txt'], self.result().files)

    def test_a_key_that_ends_it_says_the_key_the_selection_and_the_picks(self):
        screen = self.start(lambda: picker.pick_files('/r', self.FILES, keys='\x12', key_hints=[('Ctrl-R', 'refresh')]))
        self.assertEqual([('Ctrl-R', 'refresh')], [(key['name'], key['text']) for key in screen.meta()['keys']])
        screen.pick(['b.txt'], True)
        screen.select('a/x.txt')
        screen.press('\x12')
        self.assertEqual(picker.Picked('\x12', 'a/x.txt', ['b.txt']), self.result())

    def test_a_notified_key_calls_back_without_ending_it(self):
        notified = []
        screen = self.start(lambda: picker.pick_files('/r', self.FILES, notify_keys='\t',
                                                      on_notify=lambda *args: notified.append(args)))
        screen.select('a')
        screen.pick(['a/y.txt'], True)
        screen.press('\t')
        self.wait_until(lambda: notified)
        self.assertEqual([('\t', 'a', ['a/y.txt'])], notified)
        screen.quit()
        self.result()

    def test_the_selected_files_preview_and_where_the_selection_is(self):
        moves = []

        def on_selection(selection, send):
            while True:
                relpath = selection.wait_next()
                moves.append(relpath)
                send({relpath: ['about ' + relpath]})
        screen = self.start(lambda: picker.pick_files('/r', self.FILES, previews=lambda send: send({}, default=['...']),
                                                      on_selection=on_selection))
        screen.select('b.txt')
        self.wait_until(lambda: screen.preview('b.txt')['lines'] == ['about b.txt'])
        self.assertEqual(['...'], screen.preview('a/x.txt')['lines'])
        self.assertIn('b.txt', moves)
        screen.quit()
        self.result()

    def test_enter_in_the_side_tree_says_where(self):
        side = picker.Side('sorted', ['d photos', 'd photos/2026'], is_enter_picking=True)
        screen = self.start(lambda: picker.pick_files('/r', self.FILES, side=side))
        self.assertEqual('sorted', screen.meta()['side']['root'])
        screen.pick(['b.txt'], True)
        screen.side_selected = 'photos/2026'
        screen.enter(side=True)
        found = self.result()
        self.assertEqual((picker.SIDE_KEY, 'photos/2026', ['b.txt']), (found.key, found.side_selected, found.files))


class StatesTest(WebTest):
    STATES = [picker.State('skip', ' ', 'white'), picker.State('copy', '>', 'green', '>'), picker.State('remove', 'x', 'red', 'x')]

    def test_each_files_state_but_the_first_is_returned(self):
        entries = [picker.StateEntry('a/x'), picker.StateEntry('a/y', allowed=('skip', 'copy')), picker.StateEntry('b')]
        screen = self.start(lambda: picker.pick_states('/r', entries, self.STATES))
        screen.items.set_state(['a'], 'remove')
        screen.items.set_state(['b'], 'copy')
        screen.enter()
        # a/y doesn't allow remove
        self.assertEqual({'a/x': 'remove', 'b': 'copy'}, self.result().states)

    def test_a_state_the_caller_sends_is_set(self):
        screen = self.start(lambda: picker.pick_states('/r', [picker.StateEntry('a')], self.STATES,
                                                       shown_as=lambda: {'a': picker.Stated('a', 'copy', 1)}))
        self.wait_until(lambda: screen.items.info['a'].get('st') == 'copy')
        screen.enter()
        self.assertEqual({'a': 'copy'}, self.result().states)


class DirTest(WebTest):
    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['photos/2026/x.jpg', 'docs/y.txt', 'z.txt'])

    def test_a_dir_is_listed_as_its_opened_and_the_picked_ones_path_returned(self):
        screen = self.start(lambda: picker.pick_under_dir(self.root, dirs_only=True, lazy=True))
        self.assertEqual(['docs', 'photos'], [item['p'] for item in screen.items.children('')])
        self.assertEqual(['photos/2026'], [item['p'] for item in screen.items.children('photos')])
        screen.select('photos/2026')
        screen.enter()
        self.assertEqual(os.path.join(self.root, 'photos/2026'), self.result())

    def test_a_path_outside_the_dir_cant_be_picked(self):
        screen = self.start(lambda: picker.pick_under_dir(self.root))
        screen.select('../etc')
        screen.enter()
        self.assertEqual(self.root, self.result())


if __name__ == '__main__':
    unittest.main()
