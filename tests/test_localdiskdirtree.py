import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import dirtree
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
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            dst = self._copy_subdir_file()

        files = list(dst.iter_files())
        self.assertEqual(len(files), 1)
        new_file_entry = files[0]
        self.assertEqual(new_file_entry.relpath, 'subdir/file.txt')
        self.assertEqual(new_file_entry.fullpath,
                          os.path.join(self.dst_root, 'subdir/file.txt'))

    def test_copy_creates_missing_dirs(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._copy_subdir_file()
        with open(os.path.join(self.dst_root, 'subdir', 'file.txt')) as f:
            self.assertEqual(f.read(), 'content')

    def test_dry_run_copy_creates_no_dirs(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            dst = self._copy_subdir_file()
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'subdir')))
        # Nor nodes in the tree
        self.assertEqual(list(dst.iter_files()), [])


    @unittest.skipIf(os.geteuid() == 0, 'root can read anything')
    def test_scan_errors_are_kept_once(self):
        # find_files and find_dirs both hit the locked dir
        locked = os.path.join(self.src_root, 'locked')
        os.makedirs(locked)
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)

        tree = localdiskdirtree.factory(self.src_root, silent=True)

        self.assertEqual(len(tree.scan_errors), 1)
        self.assertIn('Permission denied', tree.scan_errors[0])

    def test_no_scan_errors(self):
        self.assertEqual(localdiskdirtree.factory(self.src_root, silent=True).scan_errors, [])


    def test_ctrl_c_stops_copying_and_drops_the_partial_file(self):
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        for name in ['1.txt', '2.txt', '3.txt']:
            with open(os.path.join(self.src_root, name), 'w') as f:
                f.write(name)
            src.add_file_by_relpath(name)
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)

        real_copy = localdiskdirtree.shutil.copy

        def copy(source, dest):
            if source.endswith('2.txt'):
                with open(dest, 'w') as f:
                    f.write('part')
                raise KeyboardInterrupt()
            real_copy(source, dest)

        printed = []
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.shutil.copy', side_effect=copy), \
                mock.patch('dirdelta.messages.print_line', side_effect=lambda line, *_: printed.append(line)):
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

        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.shutil.copy', side_effect=KeyboardInterrupt()), \
                mock.patch('dirdelta.messages.print_line'):
            dst.copy_inner_entries_from_dirtree(src)

        with open(os.path.join(self.dst_root, 'd', 'x.txt')) as f:
            self.assertEqual(f.read(), 'old')

    def test_ctrl_c_stops_removing(self):
        tree = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        entries = []
        for name in ['1.txt', '2.txt']:
            open(os.path.join(self.src_root, name), 'w').close()
            entries.append(tree.add_file_by_relpath(name))
        real_unlink = os.unlink

        def unlink(path):
            if path.endswith('2.txt'):
                raise KeyboardInterrupt()
            real_unlink(path)

        printed = []
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.os.unlink', side_effect=unlink), \
                mock.patch('dirdelta.messages.print_line', side_effect=lambda line, *_: printed.append(line)):
            tree.remove_files(entries)

        self.assertEqual(sorted(os.listdir(self.src_root)), ['2.txt'])
        self.assertIsNotNone(tree.get_node('2.txt'))
        self.assertEqual(printed[-1], 'Remove stopped: removed 1 of 2 files from %s' % (os.path.realpath(self.src_root),))


    def _scan(self, relpaths, **kwargs):
        for relpath in relpaths:
            path = os.path.join(self.src_root, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'w').close()
        return localdiskdirtree.factory(self.src_root, silent=True, **kwargs)

    def test_scan_has_files_and_dirs_hidden_ones_too(self):
        tree = self._scan(['visible.txt', 'sub/nested.txt', '.hidden/inner.txt', '.hidden_at_root.txt'])
        self.assertEqual(sorted(entry.relpath for entry in tree.iter_files()),
                         ['.hidden/inner.txt', '.hidden_at_root.txt', 'sub/nested.txt', 'visible.txt'])
        self.assertIsInstance(tree.get_node('sub').data, dirtree.DirEntry)
        self.assertIsInstance(tree.get_node('.hidden').data, dirtree.DirEntry)

    def test_scan_keeps_empty_dirs(self):
        os.makedirs(os.path.join(self.src_root, 'empty'))
        tree = self._scan([])
        self.assertIsInstance(tree.get_node('empty').data, dirtree.DirEntry)

    def test_scan_max_depth(self):
        tree = self._scan(['top.txt', 'a/b/deep.txt'], max_depth=2)
        self.assertIsNotNone(tree.get_node('a/b'))
        self.assertIsNone(tree.get_node('a/b/deep.txt'))
        self.assertIsNotNone(tree.get_node('top.txt'))

    def test_scan_skips_symlinks(self):
        tree_root = self.src_root
        open(os.path.join(tree_root, 'real.txt'), 'w').close()
        os.symlink(os.path.join(tree_root, 'real.txt'), os.path.join(tree_root, 'link.txt'))
        tree = self._scan([])
        self.assertIsNotNone(tree.get_node('real.txt'))
        self.assertIsNone(tree.get_node('link.txt'))

    def test_scan_names_that_arent_utf8(self):
        name = os.fsdecode(b'caf\xe9.txt')
        tree = self._scan([name])
        self.assertIsNotNone(tree.get_node(name))


if __name__ == '__main__':
    unittest.main()
