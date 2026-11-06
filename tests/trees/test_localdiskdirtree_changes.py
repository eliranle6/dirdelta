"""Removing and moving a local replica's files, and the dirs left empty"""
import os
import unittest
from unittest import mock

from dirdelta.trees import localdiskdirtree
from localdiskdirtree_support import LocalDiskDirTreeTest


class ChangesTest(LocalDiskDirTreeTest):
    """Removals and moves"""

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
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.fs.os.unlink', side_effect=unlink), \
                mock.patch('dirdelta.ui.messages.print_line', side_effect=lambda line, *_: printed.append(line)):
            tree.remove_files(entries)

        self.assertEqual(sorted(os.listdir(self.src_root)), ['2.txt'])
        self.assertIsNotNone(tree.get_node('2.txt'))
        self.assertEqual(printed[-1], 'Remove stopped: removed 1 of 2 files from %s' % (os.path.realpath(self.src_root),))

    def test_a_file_that_cant_be_removed_is_said_and_the_rest_go_on(self):
        tree = self._scan(['a.txt', 'b.txt'])
        real_unlink = os.unlink
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.ui.messages.print_line') as print_line, \
                mock.patch('dirdelta.trees.localdiskdirtree.fs.os.unlink',
                           side_effect=lambda path: (_ for _ in ()).throw(PermissionError('denied'))
                           if path.endswith('a.txt') else real_unlink(path)):
            tree.remove_files([tree.get_node('a.txt').data, tree.get_node('b.txt').data])
        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'a.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'b.txt')))
        self.assertIsNotNone(tree.get_node('a.txt'))
        print_line.assert_any_call('Remove failed: denied', 'red')

    def test_trashing_moves_files_to_the_trash_with_gio(self):
        tree = self._scan(['a.txt', 'b.txt'])
        results = {'a.txt': (1, "gio: no trash here"), 'b.txt': (0, "")}

        def run(command, **_):
            self.assertEqual(command[:2], ['gio', 'trash'])
            code, said = results[os.path.basename(command[2])]
            if code == 0:
                os.unlink(command[2])
            return mock.Mock(returncode=code, stdout=said)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.ui.messages.print_line') as print_line, \
                mock.patch('dirdelta.trees.localdiskdirtree.fs.subprocess.run', side_effect=run), \
                mock.patch('dirdelta.trees.localdiskdirtree.fs.os.unlink', wraps=os.unlink) as unlink:
            with tree.trashing():
                tree.remove_files([tree.get_node('a.txt').data, tree.get_node('b.txt').data])
            # Only gio removed b.txt (the fake's own unlink); a.txt is kept, and said
            self.assertEqual(unlink.call_count, 1)
        self.assertTrue(os.path.exists(os.path.join(self.src_root, 'a.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'b.txt')))
        print_line.assert_any_call('Remove failed: gio: no trash here', 'red')
        self.assertIn('(to the trash)', print_line.call_args_list[-1].args[0])
        # Removing for good again, after
        self.assertFalse(tree._is_trashing)
        self.assertEqual(tree.REMOVED_TO, "")

    def test_removing_files_removes_the_dirs_left_empty(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            tree = self._remove(['a/b/1.txt', 'a/b/c/2.txt', 'a/d/3.txt', 'e/4.txt'],
                                ['a/b/1.txt', 'a/b/c/2.txt', 'a/d/3.txt', 'e/4.txt', 'e/5.txt', 'f/'])
        # f was empty already, and wasn't removed from
        self.assertEqual(self._left(), ['e', 'e/5.txt', 'f'])
        self.assertNotIn('a', tree)
        self.assertIn('Removed 4 dirs left empty', self.lines)

    def test_a_dir_with_anything_left_in_it_is_kept(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._remove(['a/1.txt'], ['a/1.txt', 'a/.hidden', 'a/sub/'])
        self.assertEqual(self._left(), ['a', 'a/.hidden', 'a/sub'])

    def test_the_root_is_kept_even_if_left_empty(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self._remove(['1.txt'], ['1.txt'])
        self.assertTrue(os.path.isdir(self.src_root))
        self.assertEqual(self._left(), [])

    def test_a_dry_run_removes_no_dirs(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self._remove(['a/1.txt'], ['a/1.txt'])
        self.assertEqual(self._left(), ['a', 'a/1.txt'])

    def test_move_moves_the_file_and_removes_the_dirs_left_empty(self):
        tree = self._scan(['old/x.txt', 'keep/y.txt'])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), mock.patch('dirdelta.ui.messages.print_line'):
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
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), mock.patch('dirdelta.ui.messages.print_line'), \
                mock.patch('dirdelta.trees.localdiskdirtree.fs.os.rename', wraps=os.rename) as rename:
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
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), mock.patch('dirdelta.ui.messages.print_line'):
            self.assertEqual(tree.move_files([('x.txt', 'y.txt')]), [])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'x.txt')))

    def test_dry_run_moves_nothing(self):
        tree = self._scan(['x.txt'])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True), mock.patch('dirdelta.ui.messages.print_line'):
            self.assertEqual(tree.move_files([('x.txt', 'y.txt')]), [])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'x.txt')))


if __name__ == '__main__':
    unittest.main()
