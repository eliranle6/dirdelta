import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

from dirdelta import dirtree
from dirdelta import entries
from dirdelta import picker
from dirdelta import programs

# Stands in for treepicker: records its arguments and stdin into $FAKE_PICKER_LOG, and with
# --updates, what it read from that fd until it read $FAKE_PICKER_WAIT_FOR; then prints
# $FAKE_PICKER_OUTPUT (items separated by '|', printed '\0'-terminated) and exits with
# $FAKE_PICKER_EXIT_CODE
FAKE_PICKER = '''#!%s
import json, os, sys
stdin = sys.stdin.buffer.read().decode('utf-8', 'surrogateescape')
updates = b''
if '--updates' in sys.argv:
    fd = int(sys.argv[sys.argv.index('--updates') + 1])
    while os.environ['FAKE_PICKER_WAIT_FOR'].encode() not in updates:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        updates += chunk
with open(os.environ['FAKE_PICKER_LOG'], 'w') as log:
    json.dump({'args': sys.argv[1:], 'stdin': stdin, 'updates': updates.decode()}, log)
output = os.environ.get('FAKE_PICKER_OUTPUT', '')
sys.stdout.buffer.write(b''.join(item.encode('utf-8', 'surrogateescape') + b'\\0'
                                 for item in output.split('|') if item))
sys.exit(int(os.environ.get('FAKE_PICKER_EXIT_CODE', '0')))
''' % (sys.executable,)


class PickerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.program = os.path.join(self.tmpdir, 'treepicker')
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

    def call(self, with_label=False):
        """The arguments and the stdin items the fake treepicker got (the arguments without the
        dry run label every call has, unless with_label)"""
        with open(self.log) as f:
            log = json.load(f)
        args = log['args']
        if not with_label:
            index = args.index('--label')
            args = args[:index] + args[index + 4:]
        return args, [item for item in log['stdin'].split('\0') if item]

    def test_every_picker_shows_whether_its_a_dry_run(self):
        self.answer('x')
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            picker.pick_option(['x'])
        args, _ = self.call(with_label=True)
        self.assertEqual(args[1:5], ['--label', 'DRY RUN', '--label-color', 'green'])
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            picker.pick_under_dir('/some/dir')
        args, _ = self.call(with_label=True)
        self.assertEqual(args[1:5], ['--label', 'LIVE', '--label-color', 'red'])

    def test_a_label_after_the_dry_runs(self):
        self.answer('x')
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            picker.pick_files('/some/root', ['x'], label=('REMOVE', 'magenta'))
        args, _ = self.call(with_label=True)
        self.assertEqual(args[1:9], ['--label', 'LIVE', '--label-color', 'red',
                                     '--label', 'REMOVE', '--label-color', 'magenta'])

    def make_tree(self):
        tree = dirtree.DirTree('/some/root')
        for relpath in ['b/2.txt', 'a/1.txt', 'b/sub/3.txt', 'c.txt']:
            tree.add_file_by_relpath(relpath)
        return tree

    def test_tree_is_sent_each_dir_before_its_contents_sorted(self):
        self.answer('a/1.txt')
        picker.pick_from_tree(self.make_tree())
        args, paths = self.call()
        # Each after its type, so empty dirs show as dirs and picked files are counted
        self.assertEqual(paths, ['d a', 'f a/1.txt', 'd b', 'f b/2.txt', 'd b/sub', 'f b/sub/3.txt', 'f c.txt'])
        self.assertEqual(args, ['-0', '--typed', '--root', '/some/root', '-'])

    def test_pick_only_dirs(self):
        self.answer('a')
        picker.pick_from_tree(self.make_tree(), dirs_only=True)
        args, _ = self.call()
        self.assertIn('--dirs-only', args)
        self.answer('.')
        self.assertEqual(picker.pick_under_dir('/', dirs_only=True, lazy=True, header='Pick'), '/')
        args, _ = self.call()
        self.assertEqual(args, ['-0', '--dirs-only', '--lazy', '--header', 'Pick', '/'])

    def test_pick_from_tree_root_name(self):
        self.answer('a')
        picker.pick_from_tree(self.make_tree(), root_name='cloud/mein')
        args, _ = self.call()
        self.assertEqual(args[args.index('--root') + 1], 'cloud/mein')

    def test_pick_from_tree_returns_the_entries(self):
        self.answer('a/1.txt')
        picked = picker.pick_from_tree(self.make_tree())
        self.assertEqual([entry.relpath for entry in picked], ['a/1.txt'])
        self.assertIsInstance(picked[0], entries.FileEntry)

    def test_pick_the_root(self):
        tree = self.make_tree()
        self.answer('.')
        self.assertEqual(picker.pick_from_tree(tree), [tree.get_node('').data])

    def test_pick_files_sends_only_the_files(self):
        # treepicker adds their dirs
        self.answer('b/2.txt')
        picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt'], header='Pick\nfiles')
        args, items = self.call()
        self.assertEqual(items, ['f a/1.txt', 'f b/2.txt'])
        self.assertEqual(args, ['-0', '--typed', '--root', '/some/root', '-m', '--header', 'Pick\nfiles', '-'])

    def test_pick_files_returns_only_files(self):
        # A dir is printed when all its files are picked
        self.answer('b|b/2.txt|b/sub|b/sub/3.txt')
        picked = picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt', 'b/sub/3.txt'])
        self.assertEqual(picked, ['b/2.txt', 'b/sub/3.txt'])

    def test_picked_files_start_picked(self):
        self.answer('b/2.txt')

        # The fake records the --picked file's contents, which is gone once the picker returns
        def popen(command, **kwargs):
            with open(command[command.index('--picked') + 1], 'rb') as f:
                self.picked_file_contents = f.read()
            return real_popen(command, **kwargs)
        real_popen = picker.subprocess.Popen
        with mock.patch('dirdelta.picker.subprocess.Popen', side_effect=popen):
            picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt'], picked=['b/2.txt'])

        self.assertEqual(self.picked_file_contents, b'b/2.txt\0')

    def test_nothing_picked_passes_no_picked_file(self):
        self.answer('a/1.txt')
        picker.pick_files('/some/root', ['a/1.txt'], picked=[])
        args, _ = self.call()
        self.assertNotIn('--picked', args)

    def test_quitting_returns_none(self):
        self.answer(exit_code=1)
        self.assertIsNone(picker.pick_from_tree(self.make_tree()))
        self.assertIsNone(picker.pick_files('/some/root', ['a/1.txt']))
        self.assertIsNone(picker.pick_option(['x']))
        self.assertIsNone(picker.pick_under_dir('/some/dir'))

    def test_failure_raises(self):
        self.answer(exit_code=2)
        with self.assertRaises(picker.PickerError):
            picker.pick_option(['x'])

    def test_missing_program_raises(self):
        # (Finding it is programs.find()'s, tested in test_programs)
        with mock.patch('dirdelta.programs.find', side_effect=programs.ProgramError('not found')):
            with self.assertRaises(programs.ProgramError):
                picker.pick_option(['x'])

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

    def test_pick_option_sends_what_options_are_shown_as_as_it_changes(self):
        options = ['Copy', 'Quit']
        # Loading until asked a few times, then counted
        calls = []
        def shown_as():
            calls.append(None)
            return {'Copy': 'Copy (loading)' if len(calls) < 3 else 'Copy (3 files)'}
        os.environ['FAKE_PICKER_WAIT_FOR'] = '3 files'
        self.answer('Copy')
        with mock.patch('dirdelta.picker.SHOWN_AS_INTERVAL', 0.01):
            self.assertEqual(picker.pick_option(options, shown_as=shown_as), 'Copy')
        args, items = self.call()
        self.assertEqual(args[:-2], ['-0', '--list', '--root', 'Options'])
        self.assertEqual(args[-2], '--updates')
        self.assertEqual(items, options)
        with open(self.log) as f:
            updates = json.load(f)['updates']
        # Each change once, in order
        self.assertEqual(updates, 'Copy\tCopy (loading)\0Copy\tCopy (3 files)\0')

    def test_a_disabled_option_is_sent_as_such(self):
        os.environ['FAKE_PICKER_WAIT_FOR'] = 'disabled'
        self.answer('Quit')
        with mock.patch('dirdelta.picker.SHOWN_AS_INTERVAL', 0.01):
            picker.pick_option(['Copy', 'Quit'],
                               shown_as=lambda: {'Copy': picker.Disabled('Copy: nothing to copy')})
        with open(self.log) as f:
            updates = json.load(f)['updates']
        self.assertEqual(updates, 'Copy\tCopy: nothing to copy\tdisabled\0')

    def test_a_menu_without_shown_as_gets_no_updates(self):
        self.answer('Quit')
        picker.pick_option(['Quit'])
        args, _ = self.call()
        self.assertNotIn('--updates', args)

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
        self.assertEqual(picker.pick_files('/root', [name]), [name])
        _, items = self.call()
        self.assertEqual(items, ['f ' + name])


if __name__ == '__main__':
    unittest.main()
