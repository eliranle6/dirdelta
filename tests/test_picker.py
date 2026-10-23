import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

from dirdelta import dirtree
from dirdelta import picker

# Stands in for dirpicker: records its arguments and stdin into $FAKE_PICKER_LOG, then prints
# $FAKE_PICKER_OUTPUT (items separated by '|', printed '\0'-terminated) and exits with
# $FAKE_PICKER_EXIT_CODE
FAKE_PICKER = '''#!%s
import json, os, sys
with open(os.environ['FAKE_PICKER_LOG'], 'w') as log:
    json.dump({'args': sys.argv[1:],
               'stdin': sys.stdin.buffer.read().decode('utf-8', 'surrogateescape')}, log)
output = os.environ.get('FAKE_PICKER_OUTPUT', '')
sys.stdout.buffer.write(b''.join(item.encode('utf-8', 'surrogateescape') + b'\\0'
                                 for item in output.split('|') if item))
sys.exit(int(os.environ.get('FAKE_PICKER_EXIT_CODE', '0')))
''' % (sys.executable,)


class PickerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.program = os.path.join(self.tmpdir, 'dirpicker')
        with open(self.program, 'w') as f:
            f.write(FAKE_PICKER)
        os.chmod(self.program, os.stat(self.program).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmpdir, 'log.json')
        self.env = mock.patch.dict(os.environ, {picker.PROGRAM_ENV_VAR: self.program,
                                                'FAKE_PICKER_LOG': self.log})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmpdir)

    def answer(self, output='', exit_code=0):
        os.environ['FAKE_PICKER_OUTPUT'] = output
        os.environ['FAKE_PICKER_EXIT_CODE'] = str(exit_code)

    def call(self):
        """The arguments and the stdin items the fake dirpicker got"""
        with open(self.log) as f:
            log = json.load(f)
        return log['args'], [item for item in log['stdin'].split('\0') if item]

    def make_tree(self):
        tree = dirtree.DirTree('/some/root')
        for relpath in ['b/2.txt', 'a/1.txt', 'b/sub/3.txt', 'c.txt']:
            tree.add_file_by_relpath(relpath)
        return tree

    def test_tree_is_sent_each_dir_before_its_contents_sorted(self):
        self.answer('a/1.txt')
        picker.pick_from_tree(self.make_tree())
        args, paths = self.call()
        self.assertEqual(paths, ['a', 'a/1.txt', 'b', 'b/2.txt', 'b/sub', 'b/sub/3.txt', 'c.txt'])
        self.assertEqual(args, ['-0', '--root', '/some/root', '-'])

    def test_pick_from_tree_returns_the_entries(self):
        self.answer('a/1.txt')
        picked = picker.pick_from_tree(self.make_tree())
        self.assertEqual([entry.relpath for entry in picked], ['/a/1.txt'])
        self.assertIsInstance(picked[0], dirtree.FileEntry)

    def test_pick_the_root(self):
        tree = self.make_tree()
        self.answer('.')
        self.assertEqual(picker.pick_from_tree(tree), [tree.get_node('/').data])

    def test_pick_several(self):
        self.answer('b|b/2.txt|b/sub|b/sub/3.txt')
        picked = picker.pick_from_tree(self.make_tree(), header='Pick\nfiles', multi=True)
        self.assertEqual([entry.relpath for entry in picked], ['/b', '/b/2.txt', '/b/sub', '/b/sub/3.txt'])
        args, _ = self.call()
        self.assertEqual(args, ['-0', '--root', '/some/root', '-m', '--header', 'Pick\nfiles', '-'])

    def test_quitting_returns_none(self):
        self.answer(exit_code=1)
        self.assertIsNone(picker.pick_from_tree(self.make_tree()))
        self.assertIsNone(picker.pick_option(['x']))
        self.assertIsNone(picker.pick_under_dir('/some/dir'))

    def test_failure_raises(self):
        self.answer(exit_code=2)
        with self.assertRaises(picker.PickerError):
            picker.pick_option(['x'])

    def test_missing_program_raises(self):
        os.environ[picker.PROGRAM_ENV_VAR] = ''
        with mock.patch('shutil.which', return_value=None):
            with self.assertRaises(picker.PickerError) as context:
                picker.pick_option(['x'])
        self.assertIn('cpptree', str(context.exception))

    def test_unrunnable_program_raises(self):
        os.environ[picker.PROGRAM_ENV_VAR] = os.path.join(self.tmpdir, 'no-such-program')
        with self.assertRaises(picker.PickerError):
            picker.pick_option(['x'])

    def test_pick_option(self):
        # Labels with '/' are fine: --list keeps them flat
        options = ['Copy from /a to /b', 'Quit']
        self.answer('Copy from /a to /b')
        self.assertEqual(picker.pick_option(options, header='What now?'), 'Copy from /a to /b')
        args, items = self.call()
        self.assertEqual(args, ['-0', '--list', '--root', 'Options', '--header', 'What now?'])
        self.assertEqual(items, options)

    def test_pick_under_dir(self):
        self.answer('sub/file.txt')
        self.assertEqual(picker.pick_under_dir('/some/dir', max_depth=3), '/some/dir/sub/file.txt')
        args, items = self.call()
        self.assertEqual(args, ['-0', '--max-depth', '3', '/some/dir'])
        self.assertEqual(items, [])

    def test_pick_under_dir_root(self):
        self.answer('.')
        self.assertEqual(picker.pick_under_dir('/some/dir'), '/some/dir')

    def test_names_that_arent_utf8_come_back_as_they_were(self):
        tree = dirtree.DirTree('/root')
        name = os.fsdecode(b'caf\xe9.txt')  # Latin-1, not UTF-8
        tree.add_file_by_relpath(name)
        self.answer(name)
        self.assertEqual([entry.name for entry in picker.pick_from_tree(tree)], [name])


if __name__ == '__main__':
    unittest.main()
