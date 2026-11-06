import os
import shutil
import tempfile
import unittest

from dirdelta.trees import localscan
import helpers


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirdelta-localscan-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        helpers.make_files(self.root, ['a.txt', 'd/b.txt', 'd/e/c.txt'])

    def test_files_and_dirs_with_sizes_and_times(self):
        scan = localscan.scan(self.root)
        self.assertEqual(sorted(scan.entries), ['a.txt', 'd', 'd/b.txt', 'd/e', 'd/e/c.txt'])
        kind, size, mtime_ns = scan.entries['d/b.txt']
        self.assertEqual((kind, size), (localscan.FILE, 7))
        self.assertEqual(mtime_ns, os.stat(os.path.join(self.root, 'd/b.txt')).st_mtime_ns)
        self.assertEqual(scan.entries['d'][0], localscan.DIR)
        self.assertEqual(sorted(scan.files()), ['a.txt', 'd/b.txt', 'd/e/c.txt'])
        self.assertEqual(scan.errors, [])

    def test_other_types_arent_in_it(self):
        os.symlink('a.txt', os.path.join(self.root, 'link'))
        self.assertNotIn('link', localscan.scan(self.root).entries)

    def test_max_depth(self):
        self.assertEqual(sorted(localscan.scan(self.root, max_depth=1).entries), ['a.txt', 'd'])

    def test_names_that_arent_utf8_or_have_newlines(self):
        name = os.fsdecode(b'caf\xe9\nx.txt')
        with open(os.path.join(os.fsencode(self.root), os.fsencode(name)), 'w'):
            pass
        self.assertIn(name, localscan.scan(self.root).entries)

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_what_it_cant_read_is_said(self):
        locked = os.path.join(self.root, 'd', 'e')
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        scan = localscan.scan(self.root)
        self.assertEqual(len(scan.errors), 1)
        self.assertIn('Permission denied', scan.errors[0])

    def test_progress_may_stop_it(self):
        def progress(count):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            localscan.scan(self.root, progress=progress)


if __name__ == '__main__':
    unittest.main()
