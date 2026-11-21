"""Picking a node of a tree, or a path under a dir"""
import unittest

from dirdelta.trees import dirtree
from dirdelta.ui import picker
from picker_support import PickerTest


class TreesTest(PickerTest):
    """Trees and dirs"""

    def test_a_trees_pick_leaves_out_what_is_excluded_with_all_in_it(self):
        tree = dirtree.DirTree('/x')
        for relpath in ('meta/hashes', 'a/meta/mine', 'a/b/c', 'a/keep'):
            tree.add_file_by_relpath(relpath)
        self.assertEqual(sorted(path[2:] for path in picker.trees._tree_paths(tree, ['meta', 'a/b'])),
                         ['a', 'a/keep', 'a/meta', 'a/meta/mine'])

    def test_tree_is_sent_each_dir_before_its_contents_sorted(self):
        self.answer('a/1.txt')
        picker.pick_from_tree(self.make_tree())
        args, paths = self.call()
        # Each after its type, so empty dirs show as dirs and picked files are counted
        self.assertEqual(paths, ['d a', 'f a/1.txt', 'd b', 'f b/2.txt', 'd b/sub', 'f b/sub/3.txt', 'f c.txt'])
        self.assertEqual(args, ['-0', '--typed', '--root', '/some/root', '-'])

    def test_pick_only_dirs(self):
        self.answer('a')
        picker.pick_from_tree(self.make_tree(), dirs_only=True)
        args, _ = self.call()
        self.assertIn('--dirs-only', args)
        self.answer('.')
        self.assertEqual(picker.pick_under_dir('/', dirs_only=True, lazy=True, header='Pick'), '/')
        args, _ = self.call()
        self.assertEqual(args, ['-0', '--dirs-only', '--lazy', '--header', 'Pick', '/'])

    def test_pick_the_root(self):
        tree = self.make_tree()
        self.answer('.')
        self.assertEqual(picker.pick_from_tree(tree), [tree.get_node('').data])

    def test_pick_from_tree_with_keys_says_which_ended_it(self):
        tree = self.make_tree()
        self.answer('n|a')
        self.assertEqual(picker.pick_from_tree(tree, keys='n'), ('n', [tree.get_node('a').data]))
        args, _ = self.call()
        self.assertEqual(args[args.index('--expect') + 1], 'n')
        self.assertIn('--print-selection', args)
        # Enter: no key, the selected one picked
        self.answer('|.|.')
        self.assertEqual(picker.pick_from_tree(tree, keys='n'), ('', [tree.get_node('').data]))

    def test_pick_under_dir_with_keys_says_which_ended_it(self):
        self.answer('n|a/b')
        self.assertEqual(picker.pick_under_dir('/r', keys='n'), ('n', '/r/a/b'))
        self.answer('|.|.')
        self.assertEqual(picker.pick_under_dir('/r', keys='n'), ('', '/r'))
        self.answer('a/b')
        self.assertEqual(picker.pick_under_dir('/r'), '/r/a/b')
        args, _ = self.call()
        self.assertNotIn('--expect', args)

    def test_pick_under_dir(self):
        self.answer('sub/file.txt')
        self.assertEqual(picker.pick_under_dir('/some/dir', max_depth=3), '/some/dir/sub/file.txt')
        args, items = self.call()
        self.assertEqual(args, ['-0', '--max-depth', '3', '/some/dir'])
        self.assertEqual(items, [])


if __name__ == '__main__':
    unittest.main()
