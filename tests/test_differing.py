import os
import shutil
import tempfile
import unittest

import helpers
from dirdelta.matching import differing
from dirdelta.trees import dirtree
from dirdelta.hashes import hashcache
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker

Change = differing.Change


class _Listed(dirtree.DirTree):
    """A tree whose files are listed as given: {relpath: (size, sha1, mtime)}, as Drive's"""
    def __init__(self, files):
        super(_Listed, self).__init__('cloud/x')
        self.files = files
        for relpath in files:
            self.add_file_by_relpath(relpath)

    def file_size(self, relpath):
        return self.files[relpath][0]

    def known_hash(self, relpath, algorithm):
        return self.files[relpath][1]

    def modified_time(self, relpath):
        return self.files[relpath][2]


class FindTest(unittest.TestCase):
    def setUp(self):
        self.a_root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-differing-a-'))
        self.b_root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-differing-b-'))
        self.addCleanup(shutil.rmtree, self.a_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.b_root, ignore_errors=True)

    def write(self, root, relpath, content, mtime=None):
        helpers.make_files(root, [relpath])
        path = os.path.join(root, relpath)
        with open(path, 'w') as f:
            f.write(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def find(self):
        return differing.find(localdiskdirtree.LocalReplica(self.a_root), localdiskdirtree.LocalReplica(self.b_root))

    def test_files_of_other_sizes_differ_and_the_rest_dont(self):
        self.write(self.a_root, 'same.txt', 'abc')
        self.write(self.b_root, 'same.txt', 'abc')
        self.write(self.a_root, 'sub/grown.txt', 'abcdef', 2000)
        self.write(self.b_root, 'sub/grown.txt', 'abc', 1000)
        self.write(self.a_root, 'only_a.txt', 'x')
        self.write(self.b_root, 'only_b.txt', 'y')
        self.assertEqual(self.find(), {'sub/grown.txt': Change(6, 3, 2000, 1000, differing.BY_SIZE)})

    def test_files_of_the_same_size_differ_only_if_both_hashes_are_known_and_differ(self):
        for relpath, hashes in (('known.txt', ('h1', 'h2')), ('same.txt', ('h1', 'h1')),
                                ('half.txt', ('h1', None))):
            for root, value in zip((self.a_root, self.b_root), hashes):
                path = self.write(root, relpath, 'abc' if root == self.a_root else 'xyz', 1000)
                if value is not None:
                    hashcache.put(path, {differing.ALGORITHM: value})
        self.assertEqual(self.find(), {'known.txt': Change(3, 3, 1000, 1000, differing.BY_CONTENTS)})

    def test_whats_kept_in_a_replica_isnt_one_of_its_files(self):
        self.write(self.a_root, 'meta/hashes.sqlite', 'abcdef')
        self.write(self.b_root, 'meta/hashes.sqlite', 'abc')
        self.assertEqual(self.find(), {})

    def test_drives_files_by_their_sizes_and_sha1s_and_without_a_size_not_at_all(self):
        a = _Listed({'a': (1, None, 5), 'b': (2, 's1', 5), 'doc': (None, None, 5), 'c': (2, 's1', 5)})
        b = _Listed({'a': (2, None, 9), 'b': (2, 's2', 9), 'doc': (None, None, 9), 'c': (2, 's1', 5)})
        self.assertEqual(differing.find(a, b), {'a': Change(1, 2, 5, 9, differing.BY_SIZE),
                                                'b': Change(2, 2, 5, 9, differing.BY_CONTENTS)})

    def test_theyre_in_order_each_dirs_together(self):
        a = _Listed({'a b/x': (1, None, None), 'a/x': (1, None, None), 'a.txt': (1, None, None)})
        b = _Listed({'a b/x': (2, None, None), 'a/x': (2, None, None), 'a.txt': (2, None, None)})
        self.assertEqual(list(differing.find(a, b)), ['a/x', 'a b/x', 'a.txt'])


class ChangeTest(unittest.TestCase):
    def test_flipped_is_the_other_way(self):
        self.assertEqual(differing.flipped({'x': Change(1, 2, 10, 20, differing.BY_SIZE)}),
                         {'x': Change(2, 1, 20, 10, differing.BY_SIZE)})

    def test_which_is_newer(self):
        self.assertEqual(differing.newer(Change(1, 2, 100, 50, differing.BY_SIZE)), 1)
        self.assertEqual(differing.newer(Change(1, 2, 50, 100, differing.BY_SIZE)), -1)
        # Within FAT's 2 s, or unknown: as new
        self.assertEqual(differing.newer(Change(1, 2, 100, 101.5, differing.BY_SIZE)), 0)
        self.assertEqual(differing.newer(Change(1, 2, None, 100, differing.BY_SIZE)), 0)

    def test_the_tag_says_which_is_newer_and_how_they_differ(self):
        self.assertEqual(differing.tag(Change(2200000, 2000000, 100, 50, differing.BY_SIZE)),
                         "[> newer here, 2.1 MB vs 1.9 MB]")
        self.assertEqual(differing.tag(Change(3, 3, 50, 100, differing.BY_CONTENTS)),
                         "[< older here, same size, other contents]")
        self.assertEqual(differing.tag(Change(3, 4, None, None, differing.BY_SIZE)), "[≠ 3 B vs 4 B]")
        # Sizes that would look the same are in bytes
        self.assertEqual(differing.tag(Change(2000, 2001, None, None, differing.BY_SIZE)), "[≠ 2000 B vs 2001 B]")

    def test_the_tags_color_says_which_side_is_newer(self):
        self.assertEqual(differing.style(Change(1, 2, 100, 50, differing.BY_SIZE)), 'blue')
        self.assertEqual(differing.style(Change(1, 2, 50, 100, differing.BY_SIZE)), 'red')
        self.assertEqual(differing.style(Change(1, 2, None, 100, differing.BY_SIZE)), 'yellow')
        self.assertIn('red', differing.styled_tag(Change(1, 2, 50, 100, differing.BY_SIZE)))

    def test_the_preview_shows_both_and_what_copy_does(self):
        lines = [picker.unstyled(line) for line in differing.preview_lines(
            Change(5, 3, 2000000000, 1000000000, differing.BY_SIZE), 'cloud/b')]
        self.assertEqual(lines[0], "> Another version is in cloud/b")
        self.assertTrue(lines[1].startswith("Here:  5 B, modified ") and lines[1].endswith(" (newer)"), lines[1])
        self.assertTrue(lines[2].startswith("There: 3 B, modified ") and "newer" not in lines[2], lines[2])
        self.assertEqual(lines[-3:-1], ["Copy replaces the one there", "(Drive keeps it as an older version)."])
        self.assertIn("(it goes to the trash).", differing.preview_lines(Change(5, 3, None, None, differing.BY_SIZE), '/b'))
        self.assertNotIn("Copy replaces the one there",
                         differing.preview_lines(Change(5, 3, None, None, differing.BY_SIZE), 'b', can_replace=False))
        self.assertIn("Same size, other contents (by their hashes)",
                      differing.preview_lines(Change(3, 3, None, None, differing.BY_CONTENTS), 'b'))


if __name__ == '__main__':
    unittest.main()
