"""Picking files: what's sent, what comes back, the keys, and the tree beside them"""
import os
import unittest
from unittest import mock

from dirdelta.ui import picker
from picker_support import PickerTest


class FilesTest(PickerTest):
    """Files"""

    def test_pick_files_sends_only_the_files(self):
        # treepicker adds their dirs
        self.answer('b/2.txt')
        picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt'], header='Pick\nfiles')
        args, items = self.call()
        self.assertEqual(items, ['f a/1.txt', 'f b/2.txt'])
        self.assertEqual(args, ['-0', '--typed', '--root', '/some/root', '-m', '--print-selection',
                                '--header', 'Pick\nfiles', '-'])

    def test_pick_files_returns_only_files_and_the_selection(self):
        # The selection first; a dir is printed when all its files are picked
        self.answer('b/sub|b|b/2.txt|b/sub|b/sub/3.txt')
        picked = picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt', 'b/sub/3.txt'])
        self.assertEqual(picked, picker.Picked('', 'b/sub', ['b/2.txt', 'b/sub/3.txt']))
        # The root is ''
        self.answer('.|a/1.txt')
        self.assertEqual(picker.pick_files('/r', ['a/1.txt']).selected, '')

    def test_picked_files_start_picked(self):
        self.answer('b/2.txt')

        # The fake records the --picked file's contents, which is gone once the picker returns
        def popen(command, **kwargs):
            with open(command[command.index('--picked') + 1], 'rb') as f:
                self.picked_file_contents = f.read()
            return real_popen(command, **kwargs)
        real_popen = picker.command.subprocess.Popen
        with mock.patch('dirdelta.ui.picker.command.subprocess.Popen', side_effect=popen):
            picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt'], picked=['b/2.txt'])

        self.assertEqual(self.picked_file_contents, b'b/2.txt\0')

    def test_a_key_pressed_twice_comes_doubled(self):
        # cc
        self.answer('c|b/sub|b/2.txt')
        self.assertEqual(picker.pick_files('/r', ['a/1.txt', 'b/2.txt'], keys='r', twice_keys='c'),
                         picker.Picked('cc', 'b/sub', ['b/2.txt']))
        args, _ = self.call()
        self.assertEqual(args[args.index('--expect-twice') + 1], 'c')
        self.answer('c|a/b')
        self.assertEqual(picker.pick_under_dir('/r', keys='n', twice_keys='c'), ('cc', '/r/a/b'))
        self.answer('c|a/b')
        self.assertEqual(picker.pick_under_dir('/r', twice_keys='c'), ('cc', '/r/a/b'))
        args, _ = self.call()
        self.assertEqual(args[args.index('--expect-twice') + 1], 'c')
        self.assertNotIn('--expect', args)

    def test_another_key_in_the_side_tree_says_itself(self):
        self.answer(picker.SIDE_KEY + '|a|docs|d|a/1.txt')
        side = picker.Side('sorted', ['d docs'], True, keys='d:', key_hints=[('d', 'remove')])
        chosen = picker.pick_files('/root', ['a/1.txt'], side=side)
        self.assertEqual(chosen.side_selected, 'docs')
        self.assertEqual(chosen.side_pressed, 'd')
        self.assertEqual(chosen.files, ['a/1.txt'])
        args, _ = self.call()
        self.assertEqual(args[args.index('--side-expect') + 1], 'd:')
        self.assertEqual(args[args.index('--side-hint') + 1:args.index('--side-hint') + 3], ['d', 'remove'])

    def test_enter_in_the_side_tree_with_other_keys_says_nothing_pressed(self):
        self.answer(picker.SIDE_KEY + '|a|docs||a/1.txt')
        side = picker.Side('sorted', ['d docs'], True, keys='d:')
        chosen = picker.pick_files('/root', ['a/1.txt'], side=side)
        self.assertEqual((chosen.side_selected, chosen.side_pressed, chosen.files), ('docs', '', ['a/1.txt']))

    def test_enter_in_the_side_tree_says_its_selection(self):
        self.answer(picker.SIDE_KEY + '|a|docs|a/1.txt')
        side = picker.Side('sorted', ['d docs'], True)
        self.assertEqual(picker.pick_files('/r', ['a/1.txt'], side=side),
                         picker.Picked(picker.SIDE_KEY, 'a', ['a/1.txt'], 'docs'))
        args, _ = self.call()
        self.assertEqual(args[args.index('--side-root') + 1], 'sorted')
        self.assertEqual(args[args.index('--side-key') + 1], picker.SIDE_KEY)

    def test_it_can_start_in_the_side_tree(self):
        for start, argument in (('docs', 'docs'), ('', '.')):
            self.answer('|a|a/1.txt')
            picker.pick_files('/r', ['a/1.txt'], side=picker.Side('sorted', ['d docs'], True, start=start))
            args, _ = self.call()
            self.assertEqual(args[args.index('--side-start') + 1], argument)
        self.answer('|a|a/1.txt')
        picker.pick_files('/r', ['a/1.txt'], side=picker.Side('sorted', ['d docs'], True))
        self.assertNotIn('--side-start', self.call()[0])

    def test_pick_files_starts_on_the_selected(self):
        self.answer('a/1.txt')
        picker.pick_files('/r', ['a/1.txt'], selected='a')
        args, _ = self.call()
        self.assertEqual(args[args.index('--select') + 1], 'a')
        picker.pick_files('/r', ['a/1.txt'], selected='')
        args, _ = self.call()
        self.assertEqual(args[args.index('--select') + 1], '.')

    def test_notify_keys_tell_of_the_selection_and_the_picks(self):
        os.environ['FAKE_PICKER_NOTIFY'] = '\t|a|a/1.txt|a;\t|.'
        self.answer('.')
        notified = []
        picker.pick_files('/r', ['a/1.txt', 'b.txt'], notify_keys='\t',
                          on_notify=lambda *args: notified.append(args))
        args, _ = self.call()
        self.assertEqual(args[args.index('--notify') + 1], '\t')
        # The picks are files only (a dir all of whose files are picked is printed too); the root is ''
        self.assertEqual(notified, [('\t', 'a', ['a/1.txt']), ('\t', '', [])])


if __name__ == '__main__':
    unittest.main()
