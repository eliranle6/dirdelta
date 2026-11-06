"""Copying into a local replica: dirs made, Ctrl-C, replacing a file, its time kept"""
import os
import unittest
from unittest import mock

from dirdelta.trees import localdiskdirtree
from localdiskdirtree_support import LocalDiskDirTreeTest


class CopiesTest(LocalDiskDirTreeTest):
    """Copies"""

    def test_copy_creates_missing_dirs(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._copy_subdir_file()
        with open(os.path.join(self.dst_root, 'subdir', 'file.txt')) as f:
            self.assertEqual(f.read(), 'content')

    def test_dry_run_copy_creates_no_dirs(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            dst = self._copy_subdir_file()
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'subdir')))
        # Nor nodes in the tree
        self.assertEqual(list(dst.iter_files()), [])

    def test_ctrl_c_stops_copying_and_drops_the_partial_file(self):
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        for name in ['1.txt', '2.txt', '3.txt']:
            with open(os.path.join(self.src_root, name), 'w') as f:
                f.write(name)
            src.add_file_by_relpath(name)
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)

        real_copy = localdiskdirtree.copying.shutil.copy2

        def copy(source, dest):
            if source.endswith('2.txt'):
                with open(dest, 'w') as f:
                    f.write('part')
                raise KeyboardInterrupt()
            real_copy(source, dest)

        printed = []
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=copy), \
                mock.patch('dirdelta.ui.messages.print_line', side_effect=lambda line, *_: printed.append(line)):
            dst.copy_inner_entries_from_dirtree(src)

        self.assertEqual(sorted(os.listdir(self.dst_root)), ['1.txt'])
        self.assertIsNone(dst.get_node('2.txt'))
        self.assertIn('Stopped (Ctrl-C)', printed)
        self.assertEqual(printed[-1], 'Copy stopped: copied 1 of 3 files to %s' % (os.path.realpath(self.dst_root),))

    def test_ctrl_c_while_copying_keeps_a_file_that_was_there(self):
        # A file the tree didn't know of (e.g. find couldn't read it) isn't deleted
        os.makedirs(os.path.join(self.src_root, 'd'))
        with open(os.path.join(self.src_root, 'd', 'x.txt'), 'w') as f:
            f.write('new')
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        src.add_file_by_relpath('d/x.txt')
        os.makedirs(os.path.join(self.dst_root, 'd'))
        with open(os.path.join(self.dst_root, 'd', 'x.txt'), 'w') as f:
            f.write('old')
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)

        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=KeyboardInterrupt()), \
                mock.patch('dirdelta.ui.messages.print_line'):
            dst.copy_inner_entries_from_dirtree(src)

        with open(os.path.join(self.dst_root, 'd', 'x.txt')) as f:
            self.assertEqual(f.read(), 'old')

    def test_a_copy_replacing_a_file_sends_the_old_one_to_the_trash(self):
        dst, trash, listener = self.replace()
        with open(os.path.join(self.dst_root, 'a.txt')) as f:
            self.assertEqual(f.read(), 'new version')
        with open(os.path.join(trash, 'a.txt')) as f:
            self.assertEqual(f.read(), 'old')
        self.assertEqual(sorted(os.listdir(self.dst_root)), ['a.txt'])
        self.assertTrue(dst.has_file('a.txt'))
        # What listens forgets the old one, then knows the new one
        self.assertEqual([call[0] for call in listener.method_calls], ['remove', 'add'])
        self.assertFalse(dst._is_replacing)

    def test_a_replacing_copy_that_fails_leaves_the_old_one(self):
        def copy(src, dst):
            with open(dst, 'w') as f:
                f.write('par')
            raise OSError('disk full')
        dst, trash, listener = self.replace(copy=copy)
        with open(os.path.join(self.dst_root, 'a.txt')) as f:
            self.assertEqual(f.read(), 'old')
        self.assertEqual(os.listdir(trash), [])
        # No part of the copy left next to it
        self.assertEqual(sorted(os.listdir(self.dst_root)), ['a.txt'])
        self.assertEqual(listener.method_calls, [])

    def test_a_copy_keeps_its_modification_time(self):
        os.makedirs(os.path.join(self.src_root, 'sub'))
        path = os.path.join(self.src_root, 'sub', 'file.txt')
        with open(path, 'w') as f:
            f.write('content')
        os.utime(path, (1000000, 1000000))
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        src.add_file_by_relpath('sub/file.txt')
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)
        with mock.patch('dirdelta.ui.messages.print_line'), mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            dst.copy_inner_entries_from_dirtree(src)
        self.assertEqual(dst.modified_time('sub/file.txt'), 1000000)
        self.assertIsNone(dst.modified_time('nope'))


if __name__ == '__main__':
    unittest.main()
