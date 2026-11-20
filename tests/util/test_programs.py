import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from dirdelta.util import programs


class FindTest(unittest.TestCase):
    """Where programs.find() looks for a program (here 'prog')"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.python_dir = os.path.join(self.tmpdir, 'python-bin')
        self.build_dir = os.path.join(self.tmpdir, 'build')
        for directory in (self.python_dir, self.build_dir):
            os.makedirs(directory)
        patcher = mock.patch('sys.executable', os.path.join(self.python_dir, 'python3'))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(programs.PROGRAMS_DIR_VARIABLE, None)
        # Not run from a copy of the repo, unless a test makes one
        patcher = mock.patch.object(programs, 'SOURCE_ROOT', os.path.join(self.tmpdir, 'no-repo'))
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
            return programs.find('prog')

    def test_missing_program_raises(self):
        with self.assertRaises(programs.ProgramError) as context:
            self.find()
        self.assertIn('make build', str(context.exception))

    def test_the_build_said_comes_first(self):
        # bin/python's and make's, when running from source
        os.environ[programs.PROGRAMS_DIR_VARIABLE] = self.build_dir
        expected = self.make_program(self.build_dir)
        self.make_program(self.python_dir)
        self.assertEqual(self.find(on_path='/bin/prog'), expected)

    def test_run_from_source_without_bin_python_finds_its_build(self):
        # bin/builddir says where this copy's build is, before a program of the same name elsewhere
        root = os.path.join(self.tmpdir, 'repo')
        os.makedirs(os.path.join(root, 'bin'))
        builddir = os.path.join(root, 'bin', 'builddir')
        with open(builddir, 'w') as f:
            f.write('#!/bin/sh\necho %s\n' % self.tmpdir)
        os.chmod(builddir, 0o755)
        programs_dir = os.path.join(self.tmpdir, 'treepicker')
        os.makedirs(programs_dir)
        expected = self.make_program(programs_dir)
        self.make_program(self.python_dir)
        with mock.patch.object(programs, 'SOURCE_ROOT', root):
            self.assertEqual(self.find(on_path='/usr/bin/prog'), expected)

    def test_next_to_python_comes_before_path(self):
        # Where make install and make deploy put it
        expected = self.make_program(self.python_dir)
        self.assertEqual(self.find(on_path='/bin/prog'), expected)

    def test_on_path(self):
        self.assertEqual(self.find(on_path='/bin/prog'), '/bin/prog')


if __name__ == '__main__':
    unittest.main()
