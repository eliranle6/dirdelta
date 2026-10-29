import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import dirtree
from dirdelta import entries
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

        real_copy = localdiskdirtree.shutil.copy2

        def copy(source, dest):
            if source.endswith('2.txt'):
                with open(dest, 'w') as f:
                    f.write('part')
                raise KeyboardInterrupt()
            real_copy(source, dest)

        printed = []
        with mock.patch('dirdelta.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.localdiskdirtree.shutil.copy2', side_effect=copy), \
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
                mock.patch('dirdelta.localdiskdirtree.shutil.copy2', side_effect=KeyboardInterrupt()), \
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


    def _remove(self, relpaths, existing):
        """Remove relpaths from a src_root holding existing (relpaths: a trailing '/' an empty dir)"""
        for relpath in existing:
            path = os.path.join(self.src_root, relpath)
            if relpath.endswith('/'):
                os.makedirs(path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as f:
                    f.write(relpath)
        tree = localdiskdirtree.factory(self.src_root, silent=True)
        with mock.patch('dirdelta.messages.print_line') as print_line:
            tree.remove_files([tree.get_node(relpath).data for relpath in relpaths])
        self.lines = [call.args[0] for call in print_line.call_args_list]
        return tree

    def _left(self):
        found = []
        for dirpath, dirnames, filenames in os.walk(self.src_root):
            for name in dirnames + filenames:
                found.append(os.path.relpath(os.path.join(dirpath, name), self.src_root))
        return sorted(found)

    def test_removing_files_removes_the_dirs_left_empty(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            tree = self._remove(['a/b/1.txt', 'a/b/c/2.txt', 'a/d/3.txt', 'e/4.txt'],
                                ['a/b/1.txt', 'a/b/c/2.txt', 'a/d/3.txt', 'e/4.txt', 'e/5.txt', 'f/'])
        # f was empty already, and wasn't removed from
        self.assertEqual(self._left(), ['e', 'e/5.txt', 'f'])
        self.assertNotIn('a', tree)
        self.assertIn('Removed 4 dirs left empty', self.lines)

    def test_a_dir_with_anything_left_in_it_is_kept(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._remove(['a/1.txt'], ['a/1.txt', 'a/.hidden', 'a/sub/'])
        self.assertEqual(self._left(), ['a', 'a/.hidden', 'a/sub'])

    def test_the_root_is_kept_even_if_left_empty(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self._remove(['1.txt'], ['1.txt'])
        self.assertTrue(os.path.isdir(self.src_root))
        self.assertEqual(self._left(), [])

    def test_a_dry_run_removes_no_dirs(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self._remove(['a/1.txt'], ['a/1.txt'])
        self.assertEqual(self._left(), ['a', 'a/1.txt'])

    def test_a_removal_says_that_empty_dirs_go_too(self):
        tree = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        self.assertEqual(tree.removal_notes(['a/1.txt']), ['Dirs left empty are removed too.'])

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
        self.assertIsInstance(tree.get_node('sub').data, entries.DirEntry)
        self.assertIsInstance(tree.get_node('.hidden').data, entries.DirEntry)

    def test_scan_keeps_empty_dirs(self):
        os.makedirs(os.path.join(self.src_root, 'empty'))
        tree = self._scan([])
        self.assertIsInstance(tree.get_node('empty').data, entries.DirEntry)

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

    def test_files_by_name_finds_them_all_with_sizes_unscanned(self):
        self._scan(['a/x.txt', 'b/x.txt', 'y.txt'])
        with open(os.path.join(self.src_root, 'y.txt'), 'w') as f:
            f.write('12345')
        tree = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        found = tree.files_by_name()
        self.assertEqual(sorted(found['x.txt']), [('a/x.txt', 0), ('b/x.txt', 0)])
        self.assertEqual(found['y.txt'], [('y.txt', 5)])
        self.assertNotIn('a', found)
        self.assertEqual(tree.file_size('y.txt'), 5)
        self.assertIsNone(tree.file_size('nope.txt'))

    def test_move_moves_the_file_and_removes_the_dirs_left_empty(self):
        tree = self._scan(['old/x.txt', 'keep/y.txt'])
        with mock.patch('dirdelta.dryrun.DRYRUN', False), mock.patch('dirdelta.messages.print_line'):
            self.assertEqual(tree.move_files([('old/x.txt', 'new/sub/x.txt')]),
                             [('old/x.txt', 'new/sub/x.txt')])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'new/sub/x.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'old')))
        self.assertIsNotNone(tree.get_node('new/sub/x.txt'))
        self.assertTrue(tree.has_file('new/sub/x.txt'))
        self.assertFalse(tree.has_file('old/x.txt'))

    def test_a_whole_dir_is_moved_as_one(self):
        tree = self._scan(['old/a.txt', 'old/sub/b.txt', 'keep/c.txt', 'keep/d.txt'])
        moves = [('old/a.txt', 'new/dir/a.txt'), ('old/sub/b.txt', 'new/dir/sub/b.txt'), ('keep/c.txt', 'k/c.txt')]
        self.assertEqual(tree.dir_moves(moves),
                         ([('old', 'new/dir', [('old/a.txt', 'new/dir/a.txt'), ('old/sub/b.txt', 'new/dir/sub/b.txt')])],
                          [('keep/c.txt', 'k/c.txt')]))
        with mock.patch('dirdelta.dryrun.DRYRUN', False), mock.patch('dirdelta.messages.print_line'), \
                mock.patch('dirdelta.localdiskdirtree.os.rename', wraps=os.rename) as rename:
            self.assertEqual(sorted(tree.move_files(moves)), sorted(moves))
        # One rename for the dir, one for the other file
        self.assertEqual(len(rename.call_args_list), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'new/dir/sub/b.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'old')))
        self.assertIsNotNone(tree.get_node('new/dir/sub/b.txt'))

    def test_a_dir_with_more_in_it_or_a_new_place_thats_taken_isnt_moved_as_one(self):
        tree = self._scan(['old/a.txt', 'old/other.txt', 'two/a.txt', 'there/x'])
        self.assertEqual(tree.dir_moves([('old/a.txt', 'new/a.txt')])[0], [])
        self.assertEqual(tree.dir_moves([('two/a.txt', 'there/a.txt')])[0], [])
        # A renamed file isn't a dir's move
        self.assertEqual(tree.dir_moves([('two/a.txt', 'new/b.txt')])[0], [])

    def test_move_never_overwrites(self):
        tree = self._scan(['x.txt', 'y.txt'])
        with mock.patch('dirdelta.dryrun.DRYRUN', False), mock.patch('dirdelta.messages.print_line'):
            self.assertEqual(tree.move_files([('x.txt', 'y.txt')]), [])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'x.txt')))

    def test_dry_run_moves_nothing(self):
        tree = self._scan(['x.txt'])
        with mock.patch('dirdelta.dryrun.DRYRUN', True), mock.patch('dirdelta.messages.print_line'):
            self.assertEqual(tree.move_files([('x.txt', 'y.txt')]), [])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'x.txt')))

    def test_content_hash_reads_the_file_and_can_be_stopped(self):
        tree = self._scan(['x.txt'])
        with open(os.path.join(self.src_root, 'x.txt'), 'wb') as f:
            f.write(b'abc')
        self.assertEqual(tree.content_hash('x.txt', 'sha1'), hashlib.sha1(b'abc').hexdigest())
        self.assertIsNone(tree.content_hash('nope.txt', 'sha1'))
        with self.assertRaises(dirtree.HashStopped):
            tree.content_hash('x.txt', 'sha1', should_stop=lambda: True)
        self.assertEqual(tree.local_path('x.txt'), os.path.join(os.path.realpath(self.src_root), 'x.txt'))

    def test_a_copy_keeps_its_modification_time(self):
        os.makedirs(os.path.join(self.src_root, 'sub'))
        path = os.path.join(self.src_root, 'sub', 'file.txt')
        with open(path, 'w') as f:
            f.write('content')
        os.utime(path, (1000000, 1000000))
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        src.add_file_by_relpath('sub/file.txt')
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)
        with mock.patch('dirdelta.messages.print_line'), mock.patch('dirdelta.dryrun.DRYRUN', False):
            dst.copy_inner_entries_from_dirtree(src)
        self.assertEqual(dst.modified_time('sub/file.txt'), 1000000)
        self.assertIsNone(dst.modified_time('nope'))

    def test_files_by_name_max_depth(self):
        self._scan(['top.txt', 'a/b/deep.txt'])
        tree = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True, max_depth=2)
        self.assertEqual(sorted(tree.files_by_name()), ['top.txt'])

    def test_scan_names_that_arent_utf8(self):
        name = os.fsdecode(b'caf\xe9.txt')
        tree = self._scan([name])
        self.assertIsNotNone(tree.get_node(name))


if __name__ == '__main__':
    unittest.main()
