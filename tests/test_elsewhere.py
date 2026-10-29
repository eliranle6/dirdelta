import os
import shutil
import tempfile
import unittest

from dirdelta import dirtree
from dirdelta import elsewhere
from dirdelta import localdiskdirtree
import helpers


class _SizedTree(dirtree.DirTree):
    """A DirTree whose files have the given sizes"""
    def __init__(self, rootpath, sizes):
        super(_SizedTree, self).__init__(rootpath)
        self._sizes = sizes
        for relpath in sizes:
            self.add_file_by_relpath(relpath)

    def file_size(self, relpath):
        return self._sizes.get(relpath)


class PreviewsTest(unittest.TestCase):
    def test_a_file_the_other_replica_lacks_by_name(self):
        src = _SizedTree('/src', {'a/x.jpg': 10})
        dst = _SizedTree('/dst', {'b/y.jpg': 10})
        self.assertEqual(elsewhere.previews(['a/x.jpg'], src, dst)['a/x.jpg'],
                         ["In /dst:", "  no file of this name", "", "This one: 10 B"])

    def test_where_the_other_replica_has_it_as_a_tree_with_sizes(self):
        src = _SizedTree('/src', {'new/x.jpg': 2048})
        dst = _SizedTree('/dst', {'old/2024/x.jpg': 2048, 'old/x.jpg': 100, 'x.jpg': 5,
                                  'old/2024/other.jpg': 2048})
        self.assertEqual(elsewhere.previews(['new/x.jpg'], src, dst)['new/x.jpg'], [
            "In /dst:",
            "  old/",
            "    2024/",
            "      x.jpg  2.0 KB, same size",
            "    x.jpg  100 B",
            "  x.jpg  5 B",
            "",
            "This one: 2.0 KB",
        ])

    def test_unknown_sizes_are_left_out(self):
        src = dirtree.DirTree('/src')
        dst = dirtree.DirTree('/dst')
        dst.add_file_by_relpath('d/x')
        self.assertEqual(elsewhere.previews(['x'], src, dst)['x'], ["In /dst:", "  d/", "    x"])

    def test_a_common_names_matches_are_cut_keeping_the_same_size_ones(self):
        sizes = {'d%02d/README' % (i,): i for i in range(elsewhere.MAX_MATCHES + 3)}
        sizes['z/README'] = 1000
        src = _SizedTree('/src', {'README': 1000})
        lines = elsewhere.previews(['README'], src, _SizedTree('/dst', sizes))['README']
        self.assertIn("    README  1000 B, same size", lines)
        self.assertIn("(and 4 more)", lines)
        self.assertEqual(sum(1 for line in lines if 'README' in line), elsewhere.MAX_MATCHES)

    def test_a_local_dir_is_found_by_find_with_sizes(self):
        root = tempfile.mkdtemp(prefix='dirdelta-elsewhere-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['dst/moved/x.txt', 'src/x.txt'])
        src = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'src'), True)
        # Not scanned, as for a dirdiff
        dst = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'dst'), True)
        self.assertEqual(elsewhere.previews(['x.txt'], src, dst)['x.txt'][1:3],
                         ["  moved/", "    x.txt  15 B"])


class FormatSizeTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(elsewhere.format_size(0), "0 B")
        self.assertEqual(elsewhere.format_size(1023), "1023 B")
        self.assertEqual(elsewhere.format_size(1536), "1.5 KB")
        self.assertEqual(elsewhere.format_size(3 * 1024 ** 2), "3.0 MB")
        self.assertEqual(elsewhere.format_size(5 * 1024 ** 4), "5120.0 GB")


if __name__ == '__main__':
    unittest.main()
