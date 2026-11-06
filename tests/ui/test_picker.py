"""Running treepicker: its arguments, quitting and failing, and the labels every picker has"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta.trees import dirtree
from dirdelta.ui import picker
from dirdelta.util import programs
from picker_support import PickerTest


class RunningTest(PickerTest):
    """Running treepicker"""

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
        with mock.patch('dirdelta.ui.picker.updates.ERRORS_LOG', log), mock.patch('sys.stderr') as stderr:
            self.assertEqual(picker.pick_option(['x'], shown_as=shown_as), 'x')
        stderr.write.assert_not_called()
        with open(log) as f:
            self.assertIn("TypeError: a bug", f.read())

    def test_a_failing_shown_as_says_so_on_the_bottom_line(self):
        log = os.path.join(tempfile.mkdtemp(prefix='dirdelta-picker-'), 'errors.log')
        self.addCleanup(shutil.rmtree, os.path.dirname(log))
        read_fd, write_fd = os.pipe()
        is_done = mock.Mock()
        is_done.wait.return_value = True
        with mock.patch('dirdelta.ui.picker.updates.ERRORS_LOG', log):
            picker.updates.send_updates(write_fd, mock.Mock(side_effect=TypeError("a bug")), is_done)
        os.close(write_fd)
        with os.fdopen(read_fd, 'rb') as pipe:
            self.assertIn(b"Something went wrong", pipe.read())

    def test_every_picker_shows_whether_its_a_dry_run(self):
        self.answer('x')
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            picker.pick_option(['x'])
        args, _ = self.call(with_label=True)
        self.assertEqual(args[1:5], ['--label', 'DRY RUN', '--label-color', 'green'])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            picker.pick_under_dir('/some/dir')
        args, _ = self.call(with_label=True)
        self.assertEqual(args[1:5], ['--label', 'LIVE', '--label-color', 'red'])

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

    def test_unrunnable_program_raises(self):
        programs.find.return_value = os.path.join(self.tmpdir, 'no-such-program')
        with self.assertRaises(picker.PickerError):
            picker.pick_option(['x'])

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


class StatusTest(unittest.TestCase):
    def test_labels_each_in_its_color(self):
        self.assertEqual(picker.segments([("a: hashed", 'green'), ("", 'red'), ("b: 40% hashed", 'orange')]),
                         "\x01green\x01a: hashed\x01orange\x01b: 40% hashed")


class UpdateLineTest(unittest.TestCase):
    def test_each_kind_of_option(self):
        self.assertEqual(picker.updates._update('a', 'A'), 'a\tA')
        self.assertEqual(picker.updates._update('a', picker.Disabled('A')), 'a\tA\tdisabled')
        # A heading: skipped when moving
        self.assertEqual(picker.updates._update('a', picker.Skipped('A')), 'a\tA\tskipped')
        self.assertEqual(picker.updates._update('a', picker.Colored('A', 'red')), 'a\tA\tcolor=red')


if __name__ == '__main__':
    unittest.main()
