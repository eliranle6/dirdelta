import os
import shutil
import tempfile
import unittest

import helpers
from dirdelta import dirdiff
from dirdelta import programs


class FilesNotInTest(unittest.TestCase):
    """Runs the real dirdiff (make test builds it)"""

    def setUp(self):
        self.src = tempfile.mkdtemp(prefix='dirstuff-dirdiff-src-')
        self.dst = tempfile.mkdtemp(prefix='dirstuff-dirdiff-dst-')
        self.addCleanup(shutil.rmtree, self.src, True)
        self.addCleanup(shutil.rmtree, self.dst, True)
        helpers.make_files(self.src, ['both.txt', 'sub/only_src.txt', 'a/b/c/deep.txt'])
        helpers.make_files(self.dst, ['both.txt', 'only_dst.txt'])

    def test_files_not_in(self):
        relpaths, errors = dirdiff.files_not_in(self.src, self.dst)
        self.assertEqual(relpaths, ['a/b/c/deep.txt', 'sub/only_src.txt'])
        self.assertEqual(errors, [])

    def test_max_depth(self):
        relpaths, _ = dirdiff.files_not_in(self.src, self.dst, max_depth=2)
        self.assertEqual(relpaths, ['sub/only_src.txt'])

    @unittest.skipIf(os.geteuid() == 0, 'root can read anything')
    def test_errors_list_what_find_could_not_read(self):
        locked = os.path.join(self.src, 'sub')
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        relpaths, errors = dirdiff.files_not_in(self.src, self.dst)
        self.assertEqual(relpaths, ['a/b/c/deep.txt'])
        self.assertEqual(len(errors), 1)
        self.assertIn('Permission denied', errors[0])

    def test_missing_dir_raises(self):
        with self.assertRaises(programs.ProgramError):
            dirdiff.files_not_in(os.path.join(self.src, 'no-such-dir'), self.dst)

    def test_names_that_arent_utf8(self):
        name = os.fsdecode(b'caf\xe9.txt')
        open(os.path.join(self.src, name), 'w').close()
        relpaths, _ = dirdiff.files_not_in(self.src, self.dst)
        self.assertIn(name, relpaths)


if __name__ == '__main__':
    unittest.main()
