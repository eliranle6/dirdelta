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


if __name__ == '__main__':
    unittest.main()
