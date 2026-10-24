import unittest

from dirdelta import dirtree


class DirTreeTest(unittest.TestCase):
    def test_add_file_creates_intermediate_dirs_and_file_node(self):
        tree = dirtree.DirTree('/roms')
        tree.add_file_by_relpath('games/mario.rom')

        files = [f.relpath for f in tree.iter_files()]
        self.assertEqual(files, ['games/mario.rom'])
        self.assertIsNotNone(tree.get_node('games'))

    def test_iter_files_excludes_directories(self):
        tree = dirtree.DirTree('/roms')
        tree.add_file_by_relpath('games/mario.rom')
        tree.create_dir_node_from_relpath_if_not_exists('empty_dir')

        self.assertEqual(len(list(tree.iter_files())), 1)

    def test_diff_returns_only_files_missing_from_self(self):
        src = dirtree.DirTree('/src')
        src.add_file_by_relpath('a.txt')
        src.add_file_by_relpath('shared/b.txt')

        dst = dirtree.DirTree('/dst')
        dst.add_file_by_relpath('shared/b.txt')

        missing = dst.get_unknown_entries_in_given_dirtree(src)
        missing_paths = [f.relpath for f in missing.iter_files()]
        self.assertEqual(missing_paths, ['a.txt'])

    def test_diff_is_empty_when_nothing_missing(self):
        src = dirtree.DirTree('/src')
        src.add_file_by_relpath('a.txt')
        dst = dirtree.DirTree('/dst')
        dst.add_file_by_relpath('a.txt')

        missing = dst.get_unknown_entries_in_given_dirtree(src)
        self.assertFalse(missing.does_dir_contain_any_files())

    def test_fullpath_reflects_real_filesystem_path(self):
        tree = dirtree.DirTree('/home/user/myroot')
        tree.add_file_by_relpath('subdir/file.txt')

        root_entry = tree.get_node('').data
        file_entry = tree.get_node('subdir/file.txt').data

        self.assertEqual(root_entry.fullpath, '/home/user/myroot')
        self.assertEqual(file_entry.fullpath, '/home/user/myroot/subdir/file.txt')
        self.assertEqual(file_entry.full_filesystem_path(),
                          '/home/user/myroot/subdir/file.txt')


if __name__ == '__main__':
    unittest.main()
