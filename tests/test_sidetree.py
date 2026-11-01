import os
import shutil
import tempfile
import unittest

import helpers
from dirdelta import clouddirtree
from dirdelta import sidetree


class ItemsTest(unittest.TestCase):
    def test_a_local_dirs_dirs_and_files_in_order(self):
        root = tempfile.mkdtemp(prefix='dirdelta-sidetree-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['b/x', 'a.txt', 'inbox/y'])
        os.makedirs(os.path.join(root, 'empty'))
        self.assertEqual(sidetree.items(root, excluded='inbox'), ['f a.txt', 'd b', 'f b/x', 'd empty'])

    def test_a_drive_trees_from_its_nodes(self):
        tree = clouddirtree.CloudDirTree('cloud/me')
        tree.add_file_by_relpath('photos/a.jpg')
        self.assertEqual(sidetree.items('cloud/me', tree), ['d photos', 'f photos/a.jpg'])


class MetaTest(unittest.TestCase):
    def test_a_replicas_meta_dir_isnt_listed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            helpers.make_files(tmpdir, ['a.txt', 'meta/hashes.sqlite'])
            self.assertEqual(sidetree.items(tmpdir), ['f a.txt'])


if __name__ == '__main__':
    unittest.main()
