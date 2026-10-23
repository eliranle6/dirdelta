import os
import shutil
import tempfile
import unittest

from dirdelta import localdiskdirtree


class LocalDiskDirTreeTest(unittest.TestCase):
    def setUp(self):
        self.src_root = tempfile.mkdtemp(prefix='dirstuff-localdiskdirtree-src-')
        self.dst_root = tempfile.mkdtemp(prefix='dirstuff-localdiskdirtree-dst-')

    def tearDown(self):
        shutil.rmtree(self.src_root, ignore_errors=True)
        shutil.rmtree(self.dst_root, ignore_errors=True)

    def test_copy_inner_entries_from_dirtree_adds_node_with_correct_paths(self):
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        src.add_file_by_relpath('subdir/file.txt')

        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)
        dst.copy_inner_entries_from_dirtree(src)

        files = list(dst.iter_files())
        self.assertEqual(len(files), 1)
        new_file_entry = files[0]
        self.assertEqual(new_file_entry.relpath, '/subdir/file.txt')
        self.assertEqual(new_file_entry.fullpath,
                          os.path.join(self.dst_root, 'subdir/file.txt'))
        self.assertTrue(os.path.isdir(os.path.join(self.dst_root, 'subdir')))


if __name__ == '__main__':
    unittest.main()
