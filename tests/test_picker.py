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
# --updates (--preview), what it read from that fd until it read $FAKE_PICKER_WAIT_FOR
# ($FAKE_PICKER_PREVIEW_WAIT_FOR), after writing $FAKE_PICKER_SELECTIONS ('|'-separated) to
# --selection's fd; then prints
# $FAKE_PICKER_OUTPUT (items separated by '|', each printed '\0'-terminated, empty ones too) and exits with
# $FAKE_PICKER_EXIT_CODE
FAKE_PICKER = '''#!%s
import json, os, sys
stdin = sys.stdin.buffer.read().decode('utf-8', 'surrogateescape')
updates = b''
def read_until(option, wait_for):
    read = b''
    if option in sys.argv:
        fd = int(sys.argv[sys.argv.index(option) + 1])
        while wait_for.encode() not in read:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            read += chunk
    return read.decode()
if '--selection' in sys.argv:
    fd = int(sys.argv[sys.argv.index('--selection') + 1])
    for path in os.environ.get('FAKE_PICKER_SELECTIONS', '').split('|'):
        os.write(fd, path.encode() + b'\\0')
if '--notify-fd' in sys.argv:
    fd = int(sys.argv[sys.argv.index('--notify-fd') + 1])
    # Records ('|'-separated items, ';'-separated records), each ended by an empty item
    for record in os.environ.get('FAKE_PICKER_NOTIFY', '').split(';'):
        os.write(fd, b''.join(item.encode() + b'\\0' for item in record.split('|')) + b'\\0')
updates = read_until('--updates', os.environ.get('FAKE_PICKER_WAIT_FOR', ''))
preview = read_until('--preview', os.environ.get('FAKE_PICKER_PREVIEW_WAIT_FOR', ''))
with open(os.environ['FAKE_PICKER_LOG'], 'w') as log:
    json.dump({'args': sys.argv[1:], 'stdin': stdin, 'updates': updates, 'preview': preview}, log)
output = os.environ.get('FAKE_PICKER_OUTPUT', '')
sys.stdout.buffer.write(b''.join(item.encode('utf-8', 'surrogateescape') + b'\\0'
                                 for item in (output.split('|') if output else [])))
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
        self.env = mock.patch.dict(os.environ, {'FAKE_PICKER_LOG': self.log})
        self.env.start()
        self.find = mock.patch('dirdelta.programs.find', return_value=self.program)
        self.find.start()

    def tearDown(self):
        self.find.stop()
        self.env.stop()
        shutil.rmtree(self.tmpdir)

    def answer(self, output='', exit_code=0):
        os.environ['FAKE_PICKER_OUTPUT'] = output
        os.environ['FAKE_PICKER_EXIT_CODE'] = str(exit_code)

    def log_entry(self, key):
        """What the fake treepicker logged as key (e.g. 'preview': what it read from that fd)"""
        with open(self.log) as f:
            return json.load(f)[key]

    def call(self, with_label=False):
        """The arguments and the stdin items the fake treepicker got (the arguments without the
        dry run label every call has, unless with_label)"""
        with open(self.log) as f:
            log = json.load(f)
        args = log['args']
        if not with_label:
            index = args.index('--label')
            args = args[:index] + args[index + 4:]
            # Nor what q does, which every call says too (see test_q_quits_or_goes_back)
            index = args.index('--key')
            if args[index + 1] == 'q':
                args = args[:index] + args[index + 3:]
        return args, [item for item in log['stdin'].split('\0') if item]

    def test_q_quits_or_goes_back(self):
        self.answer('x')
        picker.pick_option(['x'])
        args, _ = self.call(with_label=True)
        self.assertEqual(args[5:8], ['--key', 'q', 'quit'])
        with picker.place('Sync'):
            picker.pick_option(['x'])
        args, _ = self.call(with_label=True)
        self.assertEqual(args[5:8], ['--key', 'q', 'back'])
        # Unless the caller says what it does
        picker.pick_option(['x'], key_hints=[('q', 'cancel')])
        args, _ = self.call(with_label=True)
        self.assertNotIn('quit', args)
        self.assertIn('cancel', args)

    def test_a_failing_background_job_is_logged_not_printed(self):
        self.answer('x')
        log = os.path.join(tempfile.mkdtemp(prefix='dirdelta-picker-'), 'errors.log')
        self.addCleanup(shutil.rmtree, os.path.dirname(log))

        def shown_as():
            raise TypeError("a bug")
        with mock.patch('dirdelta.picker.ERRORS_LOG', log), mock.patch('sys.stderr') as stderr:
            self.assertEqual(picker.pick_option(['x'], shown_as=shown_as), 'x')
        stderr.write.assert_not_called()
        with open(log) as f:
            self.assertIn("TypeError: a bug", f.read())

    def test_a_failing_shown_as_says_so_on_the_bottom_line(self):
        sent = []

        def updates(fd, shown_as, is_done):
            pass
        log = os.path.join(tempfile.mkdtemp(prefix='dirdelta-picker-'), 'errors.log')
        self.addCleanup(shutil.rmtree, os.path.dirname(log))
        read_fd, write_fd = os.pipe()
        is_done = mock.Mock()
        is_done.wait.return_value = True
        with mock.patch('dirdelta.picker.ERRORS_LOG', log):
            picker._send_updates(write_fd, mock.Mock(side_effect=TypeError("a bug")), is_done)
        os.close(write_fd)
        with os.fdopen(read_fd, 'rb') as pipe:
            self.assertIn(b"Something went wrong", pipe.read())

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

    def test_pick_from_tree_with_keys_says_which_ended_it(self):
        tree = self.make_tree()
        self.answer('n|a')
        self.assertEqual(picker.pick_from_tree(tree, keys='n'), ('n', [tree.get_node('a').data]))
        args, _ = self.call()
        self.assertEqual(args[args.index('--expect') + 1], 'n')
        self.assertIn('--print-selection', args)
        # Enter: no key, the selected one picked
        self.answer('|.|.')
        self.assertEqual(picker.pick_from_tree(tree, keys='n'), ('', [tree.get_node('').data]))

    def test_pick_under_dir_with_keys_says_which_ended_it(self):
        self.answer('n|a/b')
        self.assertEqual(picker.pick_under_dir('/r', keys='n'), ('n', '/r/a/b'))
        self.answer('|.|.')
        self.assertEqual(picker.pick_under_dir('/r', keys='n'), ('', '/r'))
        self.answer('a/b')
        self.assertEqual(picker.pick_under_dir('/r'), '/r/a/b')
        args, _ = self.call()
        self.assertNotIn('--expect', args)

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
        real_popen = picker.subprocess.Popen
        with mock.patch('dirdelta.picker.subprocess.Popen', side_effect=popen):
            picker.pick_files('/some/root', ['a/1.txt', 'b/2.txt'], picked=['b/2.txt'])

        self.assertEqual(self.picked_file_contents, b'b/2.txt\0')

    def test_pick_files_with_keys_says_which_ended_it(self):
        self.answer('r|b/sub|b/2.txt')
        self.assertEqual(picker.pick_files('/r', ['a/1.txt', 'b/2.txt'], keys='r'),
                         picker.Picked('r', 'b/sub', ['b/2.txt']))
        args, _ = self.call()
        self.assertEqual(args[args.index('--expect') + 1], 'r')

    def test_pick_files_with_keys_ended_by_enter_returns_the_picks(self):
        self.answer('|a|a/1.txt')
        self.assertEqual(picker.pick_files('/r', ['a/1.txt', 'b/2.txt'], keys='r'),
                         picker.Picked('', 'a', ['a/1.txt']))

    def test_pick_files_without_keys_has_no_expect(self):
        self.answer('a/1.txt')
        picker.pick_files('/r', ['a/1.txt'])
        args, _ = self.call()
        self.assertNotIn('--expect', args)
        self.assertNotIn('--select', args)

    def test_pick_files_starts_on_the_selected(self):
        self.answer('a/1.txt')
        picker.pick_files('/r', ['a/1.txt'], selected='a')
        args, _ = self.call()
        self.assertEqual(args[args.index('--select') + 1], 'a')
        picker.pick_files('/r', ['a/1.txt'], selected='')
        args, _ = self.call()
        self.assertEqual(args[args.index('--select') + 1], '.')

    def test_pick_files_sends_previews_as_they_come(self):
        os.environ['FAKE_PICKER_PREVIEW_WAIT_FOR'] = 'done'
        self.answer('a/1.txt')

        def previews(send):
            send({'a/1.txt': ['In b:', '  x\ty']})
            send({'': ['root']}, default=['done'])
        picker.pick_files('/r', ['a/1.txt'], previews=previews)

        # Each line after a tab, the root as '.', the default's path empty, and a tab in a line
        # shown as '?'
        self.assertEqual(self.log_entry('preview').split('\0'),
                         ['a/1.txt\tIn b:\t  x?y', '.\troot', '\tdone', ''])

    def test_previews_stop_once_the_picker_is_gone(self):
        self.answer('a/1.txt')
        stopped = []

        def previews(send):
            try:
                while True:
                    send(default=['still going'])
            except picker.PickerClosed:
                stopped.append(True)
                raise
        picker.pick_files('/r', ['a/1.txt'], previews=previews)
        # pick_files() waited for it
        self.assertEqual(stopped, [True])

    def test_on_selection_follows_the_selection_and_sends_previews(self):
        os.environ['FAKE_PICKER_SELECTIONS'] = 'a/1.txt|.|a'
        os.environ['FAKE_PICKER_PREVIEW_WAIT_FOR'] = 'done'
        self.answer('a/1.txt')
        seen = []

        def on_selection(selection, send):
            while len(seen) < 3:
                relpath = selection.wait_next()
                # Moves between waits may come as one
                seen.append(relpath)
                if relpath == 'a':
                    break
            self.assertTrue(selection.is_at('a'))
            send({'a': ['done']})
            selection.wait_next()
        picker.pick_files('/r', ['a/1.txt'], on_selection=on_selection)
        self.assertEqual(seen[-1], 'a')
        self.assertEqual(self.log_entry('preview'), 'a\tdone\0')

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

    def test_a_selection_says_the_picker_is_gone(self):
        selection = picker.Selection()
        self.assertIsNone(selection.wait_next(timeout=0.01))
        selection._move('x')
        self.assertEqual(selection.wait_next(), 'x')
        self.assertIsNone(selection.wait_next(timeout=0.01))
        selection._close()
        with self.assertRaises(picker.PickerClosed):
            selection.wait_next()
        with self.assertRaises(picker.PickerClosed):
            selection.is_at('x')

    def test_pick_files_without_previews_passes_no_preview_fd(self):
        self.answer('a/1.txt')
        picker.pick_files('/r', ['a/1.txt'])
        args, _ = self.call()
        self.assertNotIn('--preview', args)

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
        programs.find.return_value = os.path.join(self.tmpdir, 'no-such-program')
        with self.assertRaises(picker.PickerError):
            picker.pick_option(['x'])

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
        with mock.patch('dirdelta.picker.SHOWN_AS_INTERVAL', 0.01):
            self.assertEqual(picker.pick_option(options, shown_as=shown_as), 'Copy')
        args, items = self.call()
        self.assertEqual(args[:-2], ['-0', '--list', '--root', 'dirdelta'])
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
        self.answer('.|' + name)
        self.assertEqual(picker.pick_files('/root', [name]).files, [name])
        _, items = self.call()
        self.assertEqual(items, ['f ' + name])


class TrailTest(unittest.TestCase):
    def test_the_places_entered_after_the_program(self):
        self.assertEqual(picker.trail(), 'dirdelta')
        with picker.place('Sync a \u21c4 b'):
            self.assertEqual(picker.trail('Hashing'), 'dirdelta > Sync a \u21c4 b > Hashing')
        self.assertEqual(picker.trail(), 'dirdelta')

    def test_help_args(self):
        self.assertEqual(picker._help_args([('#', 'dashboard')], ['[x]: y']),
                         ['--key', '#', 'dashboard', '--help-line', '[x]: y'])


class StatusTest(unittest.TestCase):
    def test_labels_each_in_its_color(self):
        self.assertEqual(picker.status([("a: hashed", 'green'), ("", 'red'), ("b: 40% hashed", 'orange')]),
                         "\x01green\x01a: hashed\x01orange\x01b: 40% hashed")


if __name__ == '__main__':
    unittest.main()
