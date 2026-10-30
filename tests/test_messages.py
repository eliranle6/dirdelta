import io
import os
import unittest
from unittest import mock

from dirdelta import messages


class PrintLineTest(unittest.TestCase):
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


class PrintProgressTest(unittest.TestCase):
    def setUp(self):
        self.stdout = mock.Mock()
        self.stdout.buffer = io.BytesIO()
        patcher = mock.patch('sys.stdout', self.stdout)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, messages, '_is_progress_shown', False)

    def test_each_progress_line_overwrites_the_last(self):
        self.stdout.isatty.return_value = True
        messages.print_progress('Read 1 of 3')
        messages.print_progress('Read 3 of 3')
        self.assertEqual(self.stdout.buffer.getvalue(), b'\rRead 1 of 3\x1b[K\rRead 3 of 3\x1b[K')

    def test_the_next_line_starts_after_it(self):
        self.stdout.isatty.return_value = True
        messages.print_progress('Read 3')
        messages.print_line('Done')
        messages.print_line('Next')
        self.assertEqual(self.stdout.buffer.getvalue(), b'\rRead 3\x1b[K\nDone\nNext\n')

    def test_nothing_without_a_terminal(self):
        self.stdout.isatty.return_value = False
        messages.print_progress('Read 3')
        messages.print_line('Done')
        self.assertEqual(self.stdout.buffer.getvalue(), b'Done\n')


class ProgressScreenTest(unittest.TestCase):
    def run_screen(self, is_terminal, body, label=None, screen=None):
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
            if screen is None:
                with messages.progress_screen('Copying 2 files', label):
                    body()
            else:
                screen()
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
        # Scrolling the whole screen again, the cursor below it
        self.assertTrue(escapes.endswith('\033[r\033[10;1H\n'))
        self.assertEqual(lines, b'one\n')
        input_mock.assert_called_once_with()

    def test_label_starts_the_top_line(self):
        escapes, _, _ = self.run_screen(True, lambda: None, label=('DRY RUN', 'green'))
        self.assertIn('\033[2J\033[H\033[1;30;42m DRY RUN \033[0m \033[7mCtrl-C to stop', escapes)
        self.assertIn('\033[1;30;42m DRY RUN \033[0m \033[7mDone.', escapes)

    def test_label_without_a_terminal(self):
        _, lines, _ = self.run_screen(False, lambda: None, label=('LIVE', 'red'))
        self.assertEqual(lines, b'LIVE: Copying 2 files\n')

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

    def test_show(self):
        escapes, lines, input_mock = self.run_screen(
            True, None, screen=lambda: messages.show('Nothing to copy', ['/b has all of /a'],
                                                    ('DRY RUN', 'green')))
        self.assertEqual(lines, b'/b has all of /a\n')
        # Not an action: no Ctrl-C
        self.assertNotIn('Ctrl-C', escapes)
        self.assertIn('\033[7mNothing to copy', escapes)
        self.assertIn('\033[7mPress Enter to continue: Nothing to copy', escapes)
        input_mock.assert_called_once_with()

    def test_ask(self):
        asked = {}

        def screen():
            asked['answer'] = messages.ask('The name', ['Moving a.txt'], '> ', 'a.txt')
        with mock.patch('readline.set_startup_hook') as hook:
            escapes, lines, input_mock = self.run_screen(True, None, screen=screen)
        # It starts as the default, to edit; then no more
        self.assertEqual(hook.call_args_list[-1], mock.call())
        input_mock.assert_called_once_with('> ')
        self.assertEqual(lines, b'Moving a.txt\n')
        self.assertIn('\033[7mThe name', escapes)
        # No Enter to wait for after it
        self.assertNotIn('Press Enter', escapes)
        self.assertEqual(asked['answer'], input_mock.return_value.strip.return_value)

    def test_ask_with_no_answer_is_none(self):
        for answer in ({'return_value': '  '}, {'side_effect': EOFError}, {'side_effect': KeyboardInterrupt}):
            with mock.patch('builtins.input', **answer), mock.patch('sys.stdout'), mock.patch('sys.stdin'):
                self.assertIsNone(messages.ask('The name', [], '> ', 'a.txt'))


if __name__ == '__main__':
    unittest.main()
