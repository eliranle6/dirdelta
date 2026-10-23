import argparse
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import dirpick_main
import helpers


class DirpickMainTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirstuff-dirpick-')
        helpers.make_files(self.root, ['song.mp3'])
        self.args = argparse.Namespace(dir_a_path=self.root, max_depth=None, execute=None)
        patcher = mock.patch('cursesswitch.print_string')
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_run_returns_the_picked_files_full_path(self):
        with helpers.scripted_tree_picker(lambda tree: helpers.all_files(tree)):
            self.assertEqual(dirpick_main.run(self.args), os.path.join(self.root, 'song.mp3'))

    def test_run_returns_none_when_user_quits(self):
        with helpers.scripted_tree_picker(lambda tree: None):
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
