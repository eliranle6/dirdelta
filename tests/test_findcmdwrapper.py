import os
import shutil
import tempfile
import unittest

from dirdelta import findcmdwrapper


class FindCmdWrapperTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirstuff-find-test-')
        self._make_file('visible.txt')
        self._make_file('sub/nested.txt')
        self._make_file('.hidden/inner.txt')
        self._make_file('.hidden_at_root.txt')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _make_file(self, relpath):
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'w').close()

    def test_find_files_includes_hidden_by_default(self):
        found = set(findcmdwrapper.find_files(self.root))
        expected = {
            os.path.join(self.root, 'visible.txt'),
            os.path.join(self.root, 'sub/nested.txt'),
            os.path.join(self.root, '.hidden/inner.txt'),
            os.path.join(self.root, '.hidden_at_root.txt'),
        }
        self.assertEqual(found, expected)

    def test_find_files_can_exclude_hidden(self):
        found = set(findcmdwrapper.find_files(self.root, include_hidden=False))
        expected = {
            os.path.join(self.root, 'visible.txt'),
            os.path.join(self.root, 'sub/nested.txt'),
        }
        self.assertEqual(found, expected)

    def test_find_dirs_includes_root_and_visible_subdirs_only(self):
        found = set(findcmdwrapper.find_dirs(self.root, max_depth=None, include_hidden=False))
        expected = {self.root, os.path.join(self.root, 'sub')}
        self.assertEqual(found, expected)


    @unittest.skipIf(os.geteuid() == 0, 'root can read anything')
    def test_errors_list_what_find_could_not_read(self):
        locked = os.path.join(self.root, 'locked')
        self._make_file('locked/secret.txt')
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)

        errors = []
        found = findcmdwrapper.find_files(self.root, errors=errors)

        self.assertNotIn(os.path.join(locked, 'secret.txt'), found)
        self.assertEqual(len(errors), 1)
        self.assertIn(locked, errors[0])
        self.assertIn('Permission denied', errors[0])

    def test_no_errors(self):
        errors = []
        findcmdwrapper.find_dirs(self.root, max_depth=None, errors=errors)
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
