import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import dirtree
from dirdelta import elsewhere
from dirdelta import localdiskdirtree
from dirdelta import picker
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


class _Sent(object):
    """A send() for find_previews(): keeps what's sent"""
    def __init__(self):
        self.previews = {}
        self.defaults = []

    def __call__(self, found=None, default=None):
        self.previews.update(found or {})
        if default is not None:
            self.defaults.append(default)


def _previews(relpaths, src, dst):
    sent = _Sent()
    elsewhere.find_previews(relpaths, src, dst, sent)
    return sent


class FindPreviewsTest(unittest.TestCase):
    def test_a_file_the_other_replica_lacks_by_name(self):
        src = _SizedTree('/src', {'a/x.jpg': 10})
        dst = _SizedTree('/dst', {'b/y.jpg': 10})
        self.assertEqual(_previews(['a/x.jpg'], src, dst).previews['a/x.jpg'],
                         ["This one: 10 B", "In /dst:", "  no file of this name"])

    def test_the_likeliest_first_by_size(self):
        src = _SizedTree('/src', {'new/x.jpg': 2048})
        dst = _SizedTree('/dst', {'old/2024/x.jpg': 2048, 'old/x.jpg': 100, 'x.jpg': 2000,
                                  'old/2024/other.jpg': 2048})
        self.assertEqual(_previews(['new/x.jpg'], src, dst).previews['new/x.jpg'], [
            "This one: 2.0 KB",
            "In /dst, likeliest first:",
            "  old/2024/",
            "    x.jpg  2.0 KB, same size",
            "  ./",
            "    x.jpg  2000 B",
            "  old/",
            "    x.jpg  100 B",
        ])

    def test_unknown_sizes_come_last(self):
        src = _SizedTree('/src', {'x': 5})
        dst = _SizedTree('/dst', {'a/x': None, 'b/x': 500})
        lines = _previews(['x'], src, dst).previews['x']
        self.assertEqual(lines[2:], ["  b/", "    x  500 B", "  a/", "    x"])

    def test_a_common_names_matches_are_cut_keeping_the_likeliest(self):
        sizes = {'d%02d/README' % (i,): i for i in range(elsewhere.MAX_MATCHES + 3)}
        sizes['z/README'] = 1000
        src = _SizedTree('/src', {'README': 1000})
        lines = _previews(['README'], src, _SizedTree('/dst', sizes)).previews['README']
        self.assertEqual(lines[2:4], ["  z/", "    README  1000 B, same size"])
        self.assertEqual(lines[-1], "(and 4 more)")
        self.assertEqual(sum(1 for line in lines if 'README' in line), elsewhere.MAX_MATCHES)

    def test_says_how_far_it_got_then_nothing_for_the_rest(self):
        src = _SizedTree('/src', {'a': 1, 'b': 1})
        sent = _previews(['a', 'b'], src, _SizedTree('/dst', {}))
        self.assertEqual(sent.defaults[0][-1], "Listing its files")
        self.assertEqual(sent.defaults[-1], [])
        self.assertEqual(sorted(sent.previews), ['a', 'b'])

    def test_progress_counts_the_files_matched(self):
        relpaths = ['f%d' % (i,) for i in range(3)]
        src = _SizedTree('/src', {relpath: 1 for relpath in relpaths})
        # Every check says it's time to send
        with mock.patch('dirdelta.elsewhere.SEND_INTERVAL', 0):
            sent = _previews(relpaths, src, _SizedTree('/dst', {}))
        self.assertIn("Matched 2 of 3 files", [default[-1] for default in sent.defaults if default])

    def test_stops_when_the_picker_is_gone(self):
        def send(found=None, default=None):
            raise picker.PickerClosed()
        with self.assertRaises(picker.PickerClosed):
            elsewhere.find_previews(['a'], _SizedTree('/src', {}), _SizedTree('/dst', {}), send)

    def test_a_local_dir_is_found_by_find_with_sizes(self):
        root = tempfile.mkdtemp(prefix='dirdelta-elsewhere-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['dst/moved/x.txt', 'src/x.txt'])
        src = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'src'), True)
        # Not scanned, as for a dirdiff
        dst = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'dst'), True)
        self.assertEqual(_previews(['x.txt'], src, dst).previews['x.txt'],
                         ["This one: 9 B", "In %s, likeliest first:" % (dst.displayname(),),
                          "  moved/", "    x.txt  15 B"])

    def test_a_local_dir_it_cant_list_is_said(self):
        src = _SizedTree('/src', {'x': 1})
        dst = localdiskdirtree.LocalDiskDirTree('/src', True)
        with mock.patch('dirdelta.localdiskdirtree.subprocess.Popen', side_effect=OSError("no find")):
            sent = _previews(['x'], src, dst)
        self.assertEqual(sent.defaults[-1][-1], "no find")


class FormatSizeTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(elsewhere.format_size(0), "0 B")
        self.assertEqual(elsewhere.format_size(1023), "1023 B")
        self.assertEqual(elsewhere.format_size(1536), "1.5 KB")
        self.assertEqual(elsewhere.format_size(3 * 1024 ** 2), "3.0 MB")
        self.assertEqual(elsewhere.format_size(5 * 1024 ** 4), "5120.0 GB")


if __name__ == '__main__':
    unittest.main()
