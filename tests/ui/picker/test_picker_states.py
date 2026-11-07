"""Putting files in states: what's sent to treepicker, and what comes back"""
import unittest
from unittest import mock

from dirdelta.ui import picker
from picker_support import PickerTest

STATES = [picker.State('skip', ' ', 'grey'), picker.State('to-b', '>', 'blue', '>', {'only-b': ('x', 'red')})]


class StatesTest(PickerTest):
    def pick(self, **kwargs):
        # The fake records the --states file's contents, which is gone once the picker returns
        def popen(command, **popen_kwargs):
            with open(command[command.index('--states') + 1], 'rb') as f:
                self.states_file = f.read()
            return real_popen(command, **popen_kwargs)
        real_popen = picker.command.subprocess.Popen
        entries = [picker.StateEntry('a/1.txt', 'only-a', ('skip', 'to-b')), picker.StateEntry('b/2.txt', 'only-b', (), 'to-b')]
        with mock.patch('dirdelta.ui.picker.command.subprocess.Popen', side_effect=popen):
            return picker.pick_states('/r', entries, STATES, tabs=[picker.Tab('All'), picker.Tab('B', ('only-b',))], **kwargs)

    def test_the_states_tabs_and_each_files_state_are_sent(self):
        self.answer('.|to-b\tb/2.txt')
        self.pick()
        args, items = self.call()
        self.assertEqual(items, ['f a/1.txt', 'f b/2.txt'])
        self.assertEqual(args[args.index('--state'):args.index('--state') + 10],
                         ['--state', 'skip', ' ', 'grey', '', '--state', 'to-b', '>', 'blue', '>'])
        self.assertEqual(args[args.index('--state-mark'):args.index('--state-mark') + 5],
                         ['--state-mark', 'to-b', 'only-b', 'x', 'red'])
        self.assertEqual(args[args.index('--tab'):args.index('--tab') + 6], ['--tab', 'All', '', '--tab', 'B', 'only-b'])
        self.assertEqual(self.states_file, b'skip,to-b\t\tonly-a\ta/1.txt\0\tto-b\tonly-b\tb/2.txt\0')

    def test_returns_each_files_state_and_the_selection(self):
        self.answer('b|to-b\ta/1.txt|to-b\tb/2.txt')
        self.assertEqual(self.pick(), picker.StatesPicked('b', {'a/1.txt': 'to-b', 'b/2.txt': 'to-b'}))
        self.answer('.')
        self.assertEqual(self.pick(selected='b/2.txt'), picker.StatesPicked('', {}))
        args, _ = self.call()
        self.assertEqual(args[args.index('--select') + 1], 'b/2.txt')

    def test_quitting_returns_none(self):
        self.answer('', exit_code=1)
        self.assertIsNone(self.pick())


if __name__ == '__main__':
    unittest.main()
