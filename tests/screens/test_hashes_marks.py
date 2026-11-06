"""What the file pickers show of hashing: each file's tag, and a job's files"""
import unittest
from unittest import mock

from dirdelta.hashes import hashing
from dirdelta.screens.hashes_screen import status as hash_status
from dirdelta.screens import hashes_screen
from dirdelta.ui import picker


class MarksTest(unittest.TestCase):
    def setUp(self):
        self.job = hashing.Job('/photos')
        self.job._files = {'a/x': (1, 0), 'a/y': (1, 0), 'z': (1, 0)}
        self.job._is_scanned = True

    def test_each_file_after_its_mark_then_only_the_changed_ones(self):
        marks = hashes_screen.Marks(self.job, ['a/x', 'z'], [self.job])
        first = marks()
        self.assertEqual({relpath: picker.unstyled(shown) for relpath, shown in first.items() if relpath},
                         {'a/x': 'x  ' + hash_status.NOT_HASHED_TAG, 'z': 'z  ' + hash_status.NOT_HASHED_TAG})
        # Its tag in its style
        self.assertEqual(first['z'], picker.styled([('z', None), ('  ', None), (hash_status.NOT_HASHED_TAG, 'grey')]))
        self.assertEqual(first[''], picker.segments([("photos: 0% hashed (0/3, not hashing)", 'red')]))
        # z is hashed: only it changes
        self.job._hashes['z'] = 'H'
        marks._on_hashed('z', {'sha1': 'H'})
        self.assertEqual({relpath: picker.unstyled(shown) for relpath, shown in marks().items() if relpath},
                         {'z': 'z  ' + hash_status.HASHED_TAG})
        marks.close()
        self.assertEqual(self.job._subscribers, [])

    def test_the_ones_being_hashed_and_then_not(self):
        marks = hashes_screen.Marks(self.job, ['a/x', 'z'], [self.job])
        marks()
        self.job._current.add('a/x')
        self.assertEqual(picker.unstyled(marks()['a/x']), 'x  ' + hash_status.HASHING_TAG)
        self.job._current.discard('a/x')
        self.assertEqual(picker.unstyled(marks()['a/x']), 'x  ' + hash_status.NOT_HASHED_TAG)

    def test_more_status_after_the_jobs(self):
        marks = hashes_screen.Marks(None, ['a'], [self.job], lambda: [("Claude: describing 1 file", 'yellow')])
        self.assertEqual(marks(), {'': picker.segments([("photos: 0% hashed (0/3, not hashing)", 'red'),
                                                      ("Claude: describing 1 file", 'yellow')])})


class ViewFilesTest(unittest.TestCase):
    def test_its_files_with_their_marks_and_hashes(self):
        job = hashing.Job('/photos')
        job._files = {'x': (2048, 0), 'y': (1, 0)}
        job._is_scanned = True
        job._hashes['x'] = 'abc'
        sent = {}

        class Selection(object):
            moves = ['x', 'y']

            def wait_next(self, timeout=None):
                if not self.moves:
                    raise picker.PickerClosed()
                return self.moves.pop(0)

        def view_files(rootpath, relpaths, header='', shown_as=None, on_selection=None, **_):
            self.assertEqual((rootpath, relpaths), ('/photos', ['x', 'y']))
            self.assertEqual(picker.unstyled(shown_as()['x']), 'x  ' + hash_status.HASHED_TAG)
            with self.assertRaises(picker.PickerClosed):
                on_selection(Selection(), lambda found=None, default=None: sent.update(found))
            return True
        with mock.patch('dirdelta.ui.picker.view_files', side_effect=view_files):
            hashes_screen.view_files(job)
        self.assertEqual(sent['x'], ["This one: 2.0 KB", "SHA-1:", "  abc"])
        self.assertEqual(sent['y'], ["This one: 1 B", "Not hashed yet (hashing is paused)"])


if __name__ == '__main__':
    unittest.main()
