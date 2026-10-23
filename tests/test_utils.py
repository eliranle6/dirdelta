import tempfile
import shutil
import unittest
from unittest import mock

import helpers
from dirdelta import localdiskdirtree
from dirdelta import utils


class CreateDirtreeFromArgTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirstuff-utils-')
        helpers.make_files(self.root, ['top.txt', 'a/b/deep.txt'])
        patcher = mock.patch('cursesswitch.print_line')
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_local_path_builds_local_disk_tree(self):
        tree = utils.create_dirtree_from_arg(self.root)
        self.assertIsInstance(tree, localdiskdirtree.LocalDiskDirTree)
        self.assertEqual(sorted(e.relpath for e in tree.iter_files()), ['/a/b/deep.txt', '/top.txt'])

    def test_max_depth_limits_the_scan(self):
        tree = utils.create_dirtree_from_arg(self.root, max_depth=1)
        self.assertEqual([e.relpath for e in tree.iter_files()], ['/top.txt'])

    def test_cloud_path_goes_to_the_cloud_factory(self):
        with mock.patch('dirdelta.clouddirtreefactory.factory_interactive') as factory:
            tree = utils.create_dirtree_from_arg('cloud/mein')
        factory.assert_called_once_with('cloud/mein')
        self.assertIs(tree, factory.return_value)

    def test_path_merely_containing_cloud_is_local(self):
        with mock.patch('dirdelta.clouddirtreefactory.factory_interactive') as factory, \
             self.assertRaises(SystemExit):
            utils.create_dirtree_from_arg('not-cloud/cloud')
        factory.assert_not_called()

    def test_missing_dir_exits(self):
        with self.assertRaises(SystemExit):
            utils.create_dirtree_from_arg(self.root + '/does-not-exist')


if __name__ == '__main__':
    unittest.main()
