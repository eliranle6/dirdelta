"""Menus of options: their ids, how they're shown, and as it changes"""
import json
import os
import unittest
from unittest import mock

from dirdelta.ui import picker
from picker_support import PickerTest


class MenusTest(PickerTest):
    """Menus"""

    def test_an_options_id_is_returned_and_said_by_its_line(self):
        os.environ['FAKE_PICKER_WAIT_FOR'] = 'Later'
        self.answer('Do it ')
        options = ['Do it', picker.BLANK, picker.Option(('do', 1), 'Do it', 'Now'), picker.Option('later', 'Later')]
        answer = picker.pick_option(options, selected=('do', 1), shown_as=lambda: {'later': 'Later', 'unknown': 'x'},
                                    previews_below={('do', 1): ['what']})
        self.assertEqual(answer, ('do', 1))
        self.assertEqual(self.log_entry('stdin').split('\0')[:-1], ['Do it', ' ', 'Do it ', 'Later'])
        args = self.log_entry('args')
        self.assertEqual(args[args.index('--select') + 1], 'Do it ')
        # The first updates: what they're shown as first, and by shown_as, not what it doesn't have
        updates = self.log_entry('updates').split('\0')
        self.assertIn('Do it \tNow', updates)
        self.assertIn('Later\tLater', updates)
        self.assertFalse(any('unknown' in update for update in updates))

    def test_quitting_a_menu_of_options_is_none(self):
        self.answer(exit_code=1)
        self.assertIsNone(picker.pick_option([picker.Option(1, 'a')]))

    def test_pick_option(self):
        # Labels with '/' are fine: --list keeps them flat
        options = ['Copy from /a to /b', 'Quit']
        self.answer('Copy from /a to /b')
        self.assertEqual(picker.pick_option(options, header='What now?'), 'Copy from /a to /b')
        args, items = self.call()
        self.assertEqual(args, ['-0', '--list', '--root', 'dirdelta', '--header', 'What now?'])
        self.assertEqual(items, options)

    def test_pick_option_sends_what_options_are_shown_as_as_it_changes(self):
        options = ['Copy', 'Quit']
        # Loading until asked a few times, then counted
        calls = []
        def shown_as():
            calls.append(None)
            return {'Copy': 'Copy (loading)' if len(calls) < 3 else 'Copy (3 files)'}
        os.environ['FAKE_PICKER_WAIT_FOR'] = '3 files'
        self.answer('Copy')
        with mock.patch('dirdelta.ui.picker.updates.SHOWN_AS_INTERVAL', 0.01):
            self.assertEqual(picker.pick_option(options, shown_as=shown_as), 'Copy')
        args, items = self.call()
        self.assertEqual(args[:-2], ['-0', '--list', '--root', 'dirdelta'])
        self.assertEqual(args[-2], '--updates')
        self.assertEqual(items, options)
        with open(self.log) as f:
            updates = json.load(f)['updates']
        # Each change once, in order
        self.assertEqual(updates, 'Copy\tCopy (loading)\0Copy\tCopy (3 files)\0')


class MenuLinesTest(unittest.TestCase):
    def test_each_line_is_its_own(self):
        lines, line_of, shown = picker.menus._menu_lines([picker.Skipped('Head'), 'a', picker.BLANK, picker.Option(1, 'a'),
                                                    picker.BLANK])
        self.assertEqual(lines, ['Head', 'a', ' ', 'a ', '  '])
        self.assertEqual(len(set(lines)), 5)
        self.assertEqual(line_of, {'a': 'a', 1: 'a '})
        # What's skipped isn't an option
        self.assertEqual(shown, {'Head': picker.Skipped('Head'), ' ': picker.BLANK, '  ': picker.BLANK})

    def test_a_styled_labels_line_is_its_text(self):
        self.assertEqual(picker.menus._menu_lines([picker.Skipped(picker.styled([('Head', 'bold')]))])[0], ['Head'])


class GroupedTest(unittest.TestCase):
    def test_a_blank_line_between_groups(self):
        self.assertEqual(picker.grouped([['a'], [], ['b', 'c'], ['d']]), ['a', picker.BLANK, 'b', 'c', picker.BLANK, 'd'])


class ShortcutPrefixesTest(unittest.TestCase):
    def test_the_keys_in_a_column_and_spaces_for_the_others(self):
        prefixes = picker.shortcut_prefixes(['a', 'b', 'c'], {'a': 'Ctrl-X', 'c': 'r'})
        self.assertEqual({label: picker.unstyled(text) for label, text in prefixes.items()},
                         {'a': '[Ctrl-X] ', 'b': ' ' * 9, 'c': '[r]      '})
        self.assertEqual(prefixes['a'], picker.styled([('[Ctrl-X]', 'bold'), (' ', None)]))
        # None has a key: nothing before them
        self.assertEqual(picker.shortcut_prefixes(['a'], {}), {'a': ''})


class StyledTest(unittest.TestCase):
    def test_parts_in_their_styles_and_back(self):
        text = picker.styled([('a.jpg', None), ('  ', None), ('[x]', 'bold,magenta'), ('', 'red')])
        self.assertEqual(text, '\x02\x02a.jpg\x02\x02  \x02bold,magenta\x02[x]')
        self.assertEqual(picker.unstyled(text), 'a.jpg  [x]')
        # Without styles, plain
        self.assertEqual(picker.styled([('a', None), ('b', '')]), 'ab')


class AmbientStatusTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(picker.set_ambient_status, picker.updates._ambient_status)

    def test_its_shown_by_a_picker_with_nothing_else_to_show(self):
        picker.set_ambient_status(lambda: [('hashing', 'orange')])
        self.assertEqual(picker.updates.with_ambient_status(None)(), {'': picker.segments([('hashing', 'orange')])})
        self.assertEqual(picker.updates.with_ambient_status(lambda: {'x': 'y'})(),
                         {'x': 'y', '': picker.segments([('hashing', 'orange')])})

    def test_a_pickers_own_status_comes_first(self):
        picker.set_ambient_status(lambda: [('hashing', 'orange')])
        self.assertEqual(picker.updates.with_ambient_status(lambda: {'': 'mine'})(), {'': 'mine'})

    def test_its_cleared_once_its_over(self):
        parts = [[('hashing', 'orange')], []]
        picker.set_ambient_status(lambda: parts[0])
        shown = picker.updates.with_ambient_status(None)
        self.assertEqual(shown(), {'': picker.segments(parts[0])})
        parts.pop(0)
        self.assertEqual(shown(), {'': ''})


if __name__ == '__main__':
    unittest.main()
