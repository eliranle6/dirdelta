import io
import os
import unittest
from unittest import mock

from dirdelta import messages


class PrintLineTest(unittest.TestCase):
    def setUp(self):
        messages.take_recent()

    def print_line(self, *args, **kwargs):
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        with mock.patch('sys.stdout', stdout):
            messages.print_line(*args, **kwargs)
        return stdout.buffer.getvalue()

    def test_prints_a_line(self):
        self.assertEqual(self.print_line('Copying a.mp3'), b'Copying a.mp3\n')

    def test_color(self):
        with mock.patch.dict(os.environ, {'FORCE_COLOR': '1'}):
            self.assertEqual(self.print_line('Copy failed', 'red'), b'\x1b[31mCopy failed\x1b[0m\n')

    def test_names_that_arent_utf8(self):
        name = os.fsdecode(b'caf\xe9.txt')
        self.assertEqual(self.print_line('Removing ' + name), b'Removing caf\xe9.txt\n')


    def test_recent_lines_are_kept_until_taken(self):
        self.print_line('one')
        self.print_line('two', 'red')
        self.assertEqual(messages.take_recent(), ['one', 'two'])
        self.assertEqual(messages.take_recent(), [])

    def test_only_the_last_recent_lines_are_kept(self):
        for i in range(messages.MAX_RECENT_LINES + 3):
            self.print_line('line %d' % (i,))
        recent = messages.take_recent()
        self.assertEqual(recent[0], '(3 earlier lines)')
        self.assertEqual(recent[1:], ['line %d' % (i,) for i in range(3, messages.MAX_RECENT_LINES + 3)])
        self.assertEqual(messages.take_recent(), [])



class ProgressScreenTest(unittest.TestCase):
    def setUp(self):
        messages.take_recent()

    def run_screen(self, is_terminal, body):
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        stdout.isatty.return_value = is_terminal
        written = []
        stdout.write.side_effect = written.append
        with mock.patch('sys.stdout', stdout), \
                mock.patch('sys.stdin') as stdin, \
                mock.patch('builtins.input') as input_mock, \
                mock.patch('shutil.get_terminal_size', return_value=os.terminal_size((80, 10))):
            stdin.isatty.return_value = is_terminal
            with messages.progress_screen('Copying 2 files'):
                body()
        return ''.join(written), stdout.buffer.getvalue(), input_mock

    def test_without_a_terminal_the_lines_are_just_printed(self):
        escapes, lines, input_mock = self.run_screen(False, lambda: messages.print_line('one'))
        self.assertEqual(escapes, '')
        self.assertEqual(lines, b'Copying 2 files\none\n')
        input_mock.assert_not_called()

    def test_on_a_terminal_the_title_stays_on_top_and_enter_ends_it(self):
        escapes, lines, input_mock = self.run_screen(True, lambda: messages.print_line('one'))
        # Cleared, the title on top, the rest scrolling (rows 2 to 10), then the region reset
        self.assertTrue(escapes.startswith('\033[2J\033[H'))
        self.assertIn('Ctrl-C to stop: Copying 2 files', escapes)
        self.assertIn('\033[2;10r', escapes)
        self.assertIn('Done. Press Enter to continue: Copying 2 files', escapes)
        self.assertTrue(escapes.endswith('\033[r'))
        self.assertEqual(lines, b'one\n')
        input_mock.assert_called_once_with()
        # It was read on the screen, so the next picker doesn't show it again
        self.assertEqual(messages.take_recent(), [])

    def test_ctrl_c_stops_the_action(self):
        def body():
            messages.print_line('one')
            raise KeyboardInterrupt()
        escapes, lines, _ = self.run_screen(True, body)
        self.assertIn(b'Stopped (Ctrl-C)', lines)
        self.assertIn('Stopped. Press Enter to continue: Copying 2 files', escapes)

    def test_an_action_that_stops_itself_shows_as_stopped(self):
        # E.g. copying, which catches Ctrl-C to say how many files it copied
        def body():
            messages.note_stopped()
            messages.print_line('Copied 1 of 2 files')
        escapes, lines, _ = self.run_screen(True, body)
        # Red, on a terminal
        self.assertEqual(lines, b'\x1b[31mStopped (Ctrl-C)\x1b[0m\nCopied 1 of 2 files\n')
        self.assertIn('Stopped. Press Enter to continue', escapes)

    def test_the_next_screen_starts_not_stopped(self):
        self.run_screen(True, messages.note_stopped)
        escapes, _, _ = self.run_screen(True, lambda: None)
        self.assertIn('Done. Press Enter to continue', escapes)


if __name__ == '__main__':
    unittest.main()
