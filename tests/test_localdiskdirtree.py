import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import localdiskdirtree


class LocalDiskDirTreeTest(unittest.TestCase):
    def setUp(self):
        self.src_root = tempfile.mkdtemp(prefix='dirstuff-localdiskdirtree-src-')
        self.dst_root = tempfile.mkdtemp(prefix='dirstuff-localdiskdirtree-dst-')

    def tearDown(self):
        shutil.rmtree(self.src_root, ignore_errors=True)
        shutil.rmtree(self.dst_root, ignore_errors=True)

    def _copy_subdir_file(self):
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        src.add_file_by_relpath('subdir/file.txt')
        os.makedirs(os.path.join(self.src_root, 'subdir'))
        with open(os.path.join(self.src_root, 'subdir', 'file.txt'), 'w') as f:
            f.write('content')

        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)
        with mock.patch('dirdelta.messages.print_line'):
            dst.copy_inner_entries_from_dirtree(src)
        return dst

    def test_copy_inner_entries_from_dirtree_adds_node_with_correct_paths(self):
        dst = self._copy_subdir_file()

        files = list(dst.iter_files())
        self.assertEqual(len(files), 1)
        new_file_entry = files[0]
        self.assertEqual(new_file_entry.relpath, '/subdir/file.txt')
        self.assertEqual(new_file_entry.fullpath,
                          os.path.join(self.dst_root, 'subdir/file.txt'))

    def test_copy_creates_missing_dirs(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', False):
            self._copy_subdir_file()
        with open(os.path.join(self.dst_root, 'subdir', 'file.txt')) as f:
            self.assertEqual(f.read(), 'content')

    def test_dry_run_copy_creates_no_dirs(self):
        with mock.patch('dirdelta.localdiskdirtree.DRYRUN', True):
            self._copy_subdir_file()
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'subdir')))


if __name__ == '__main__':
    unittest.main()
