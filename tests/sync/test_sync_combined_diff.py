"""d in the combined tree: a file's diff, A's version against B's, in less"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the caches' fakes)
from dirdelta.matching import differing
from dirdelta.sync.combined import diffing
from dirdelta.sync.combined import diffview
from dirdelta.sync.combined import screen
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker

REAL_RUN = subprocess.run


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for relpath, contents in (('a/notes.txt', 'one\ntwo\n'), ('a/only.txt', 'mine\n'), ('a/bin.dat', 'x\0y'),
                                  ('b/notes.txt', 'one\nthree\n'), ('b/bin.dat', 'x\0z')):
            os.makedirs(os.path.dirname(os.path.join(self.root, relpath)), exist_ok=True)
            with open(os.path.join(self.root, relpath), 'w') as f:
                f.write(contents)
        self.a = localdiskdirtree.LocalDiskDirTree(os.path.join(self.root, 'a'), silent=True)
        self.b = localdiskdirtree.LocalDiskDirTree(os.path.join(self.root, 'b'), silent=True)
        changes = differing.Changes({'notes.txt': differing.Change(8, 10, None, None, differing.BY_SIZE),
                                     'bin.dat': differing.Change(3, 3, None, None, differing.BY_SIZE)})
        self.sync = screen.CombinedSync(self.a, self.b, self.a.fullpath(), self.b.fullpath(), ['only.txt'], [], changes)
        for name, patcher in (('show', mock.patch('dirdelta.ui.messages.show')),
                              ('line', mock.patch('dirdelta.ui.messages.print_line'))):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def paged(self, relpath):
        """What diffing.show() sends less for relpath (None if it ran no less)"""
        paged = []

        def run(args, **kwargs):
            if args[0] == 'less':
                paged.append(kwargs['input'].decode())
                return subprocess.CompletedProcess(args, 0)
            return REAL_RUN(args, **kwargs)
        with mock.patch('subprocess.run', side_effect=run):
            diffing.show(self.sync, relpath)
        return paged[0] if paged else None

    def test_a_differing_files_versions_are_diffed(self):
        paged = self.paged('notes.txt')
        self.assertIn('-two', paged)
        self.assertIn('+three', paged)
        self.assertIn('a/notes.txt', paged)

    def test_a_file_only_one_has_is_diffed_against_nothing(self):
        # A's on the left: all of it removed on B's side
        self.assertIn('-mine', self.paged('only.txt'))

    def test_files_that_arent_text_arent_diffed(self):
        self.assertIsNone(self.paged('bin.dat'))
        self.assertIn("isn't text", self.show.call_args.args[1][0])

    def test_a_dir_isnt_diffed(self):
        self.assertIsNone(self.paged(''))
        self.assertIn("Select a file", self.show.call_args.args[1][0])


class IsTextTest(unittest.TestCase):
    def test_text_in_any_byte_encoding_is_text_and_binary_isnt(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        for name, data, is_text in (('utf8', 'שלום\n'.encode(), True), ('latin1', 'caf\xe9\n'.encode('latin-1'), True),
                                    ('nul', b'a\0b', False), ('controls', bytes(range(1, 31)) * 10, False)):
            path = os.path.join(root, name)
            with open(path, 'wb') as f:
                f.write(data)
            self.assertEqual(diffing.is_text(path), is_text, name)


class DiffViewTest(unittest.TestCase):
    """The right column's views of two versions"""
    A = ['one', 'two', 'three']
    B = ['one', '2', 'three', 'four']

    def view(self, view, width=41):
        return [picker.unstyled(line) for line in diffview.lines_of(view, self.A, self.B, 'a', 'b', width)]

    def test_side_by_side_lines_up_the_versions_and_marks_what_differs(self):
        lines = self.view(diffview.SIDE_BY_SIDE)
        half = (41 - 3) // 2
        self.assertEqual(lines, ['a'.ljust(half) + ' │ b',
                                 'one'.ljust(half) + '   one',
                                 'two'.ljust(half) + ' ≠ 2',
                                 'three'.ljust(half) + '   three',
                                 ''.ljust(half) + ' > four'])

    def test_unified_is_as_diff_u(self):
        self.assertEqual(self.view(diffview.UNIFIED)[2:], ['@@ -1,3 +1,4 @@', ' one', '-two', '+2', ' three', '+four'])

    def test_either_version_is_all_of_it(self):
        self.assertEqual(self.view(diffview.VERSION_A), self.A)
        self.assertEqual(self.view(diffview.VERSION_B), self.B)
