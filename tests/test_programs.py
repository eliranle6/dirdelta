import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from dirdelta import programs


class FindTest(unittest.TestCase):
    """Where programs.find() looks for a program (here 'prog', overridden by $TEST_PROG)"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.python_dir = os.path.join(self.tmpdir, 'python-bin')
        self.build_dir = os.path.join(self.tmpdir, 'build')
        for directory in (self.python_dir, self.build_dir):
            os.makedirs(directory)
        for patcher in (mock.patch.dict(os.environ, {'TEST_PROG': ''}),
                        mock.patch('sys.executable', os.path.join(self.python_dir, 'python3')),
                        mock.patch('dirdelta.programs.SOURCE_TREE_BUILD', self.build_dir)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_program(self, directory):
        path = os.path.join(directory, 'prog')
        with open(path, 'w') as f:
            f.write('#!/bin/sh\n')
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def find(self, on_path=None):
        with mock.patch('shutil.which', return_value=on_path):
            return programs.find('prog', 'TEST_PROG')

    def test_missing_program_raises(self):
        with self.assertRaises(programs.ProgramError) as context:
            self.find()
        self.assertIn('make build', str(context.exception))
        self.assertIn('$TEST_PROG', str(context.exception))

    def test_env_var_comes_first(self):
        self.make_program(self.python_dir)
        os.environ['TEST_PROG'] = '/some/prog'
        self.assertEqual(self.find(), '/some/prog')

    def test_next_to_python_comes_next(self):
        # Where make install and make deploy put it
        expected = self.make_program(self.python_dir)
        self.make_program(self.build_dir)
        self.assertEqual(self.find(on_path='/bin/prog'), expected)

    def test_source_tree_build_comes_before_path(self):
        expected = self.make_program(self.build_dir)
        self.assertEqual(self.find(on_path='/bin/prog'), expected)

    def test_on_path(self):
        self.assertEqual(self.find(on_path='/bin/prog'), '/bin/prog')


if __name__ == '__main__':
    unittest.main()
