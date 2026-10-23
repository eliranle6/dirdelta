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


if __name__ == '__main__':
    unittest.main()
