import os
import tempfile
import unittest
import zipfile

from dirdelta.util import archives


class MembersTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, 'z.zip')

    def make(self, names):
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name in names:
                archive.writestr(name, 'hello')

    def test_its_files_sorted_without_its_dirs(self):
        self.make(['b.txt', 'a/', 'a/c.txt'])
        found = archives.members(self.path)
        self.assertEqual([member.relpath for member in found], ['a/c.txt', 'b.txt'])
        self.assertEqual(found[0].size, 5)

    def test_odd_paths_are_made_relative(self):
        self.make(['/abs.txt', '../up.txt', 'a/../b.txt', 'win\\dows.txt'])
        self.assertEqual([member.relpath for member in archives.members(self.path)],
                         ['abs.txt', 'b.txt', 'up.txt', 'win/dows.txt'])

    def test_one_thats_not_a_zip(self):
        with open(self.path, 'w') as f:
            f.write('not a zip')
        with self.assertRaises(archives.ArchiveError):
            archives.members(self.path)

    def test_is_archive(self):
        self.assertTrue(archives.is_archive('a/B.ZIP'))
        self.assertFalse(archives.is_archive('a.zip.txt'))

    def test_said(self):
        self.make(['a.txt', 'b.txt'])
        said = archives.said(archives.members(self.path), 1)
        self.assertIn('2 files', said)
        self.assertIn('the first 1', said)
        self.assertIn('a.txt', said)
        self.assertNotIn('b.txt', said)


if __name__ == '__main__':
    unittest.main()
