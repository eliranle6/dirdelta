import argparse
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import dirpick_main
from dirdelta import dirtree
import helpers


class DirpickMainTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirstuff-dirpick-')
        helpers.make_files(self.root, ['song.mp3'])
        self.args = argparse.Namespace(dir_a_path=self.root, max_depth=None, execute=None)
        patcher = mock.patch('cursesswitch.print_line')
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_local_dir_is_scanned_by_dirpicker(self):
        picked = os.path.join(self.root, 'song.mp3')
        with helpers.scripted_dir_picker(picked) as pick_under_dir:
            self.assertEqual(dirpick_main.run(self.args), picked)
        pick_under_dir.assert_called_once_with(os.path.realpath(self.root), None)

    def test_local_dir_max_depth_is_passed_on(self):
        self.args.max_depth = 3
        with helpers.scripted_dir_picker(self.root) as pick_under_dir:
            dirpick_main.run(self.args)
        pick_under_dir.assert_called_once_with(os.path.realpath(self.root), 3)

    def test_run_returns_none_when_user_quits(self):
        with helpers.scripted_dir_picker(None):
            self.assertIsNone(dirpick_main.run(self.args))

    def test_missing_dir_exits(self):
        self.args.dir_a_path = os.path.join(self.root, 'no-such-dir')
        with self.assertRaises(SystemExit):
            dirpick_main.run(self.args)

    def test_cloud_tree_is_picked_from_its_dirtree(self):
        tree = dirtree.DirTree('cloud/mein')
        tree.add_file_by_relpath('music/song.mp3')
        self.args.dir_a_path = 'cloud/mein'
        with mock.patch('dirdelta.utils.create_dirtree_from_arg', return_value=tree), \
                helpers.scripted_tree_picker(helpers.all_files):
            self.assertEqual(dirpick_main.run(self.args), 'cloud/mein/music/song.mp3')

    def test_cloud_tree_quit(self):
        self.args.dir_a_path = 'cloud/mein'
        with mock.patch('dirdelta.utils.create_dirtree_from_arg', return_value=dirtree.DirTree('cloud/mein')), \
                helpers.scripted_tree_picker(lambda tree: None):
            self.assertIsNone(dirpick_main.run(self.args))

    def test_use_picked_path_prints_it_without_execute(self):
        with mock.patch('builtins.print') as print_mock:
            dirpick_main.use_picked_path('/some/file')
        print_mock.assert_called_once_with('/some/file')

    def test_use_picked_path_runs_the_program_with_execute(self):
        with mock.patch('os.execvp') as execvp:
            dirpick_main.use_picked_path('/some/file', execute='vlc')
        execvp.assert_called_once_with('vlc', ['vlc', '/some/file'])


if __name__ == '__main__':
    unittest.main()
