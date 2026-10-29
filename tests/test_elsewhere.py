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
    """A DirTree whose files have the given sizes (and dates taken)"""
    def __init__(self, rootpath, sizes, dates=None):
        super(_SizedTree, self).__init__(rootpath)
        self._sizes = sizes
        self._dates = dates or {}
        self.dates_read = []
        for relpath in sizes:
            self.add_file_by_relpath(relpath)

    def file_size(self, relpath):
        return self._sizes.get(relpath)

    def date_taken(self, relpath):
        self.dates_read.append(relpath)
        return self._dates.get(relpath)


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
    elsewhere.find_previews(relpaths, src, elsewhere.Index(dst), sent)
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
            "    surely this file, moved",
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
        self.assertEqual(lines[2:5], ["  z/", "    README  1000 B, same size", "    surely this file, moved"])
        self.assertEqual(lines[-1], "(and 4 more)")
        self.assertEqual(sum(1 for line in lines if line.startswith('    README')), elsewhere.MAX_MATCHES)

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
            elsewhere.find_previews(['a'], _SizedTree('/src', {}), elsewhere.Index(_SizedTree('/dst', {})),
                                    send)

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

    def test_siblings_in_a_matchs_dir_make_it_likelier(self):
        # photos/ was moved to old/photos/; other/ has one of its names, of a different size
        src = _SizedTree('/src', {'photos/%d.jpg' % (i,): i for i in range(5)})
        dst = _SizedTree('/dst', dict({'old/photos/%d.jpg' % (i,): 100 + i for i in range(5)},
                                      **{'other/0.jpg': 50}))
        sent = _previews(sorted(src._sizes), src, dst)
        lines = sent.previews['photos/0.jpg']
        self.assertEqual(lines[2:5], ["  old/photos/", "    0.jpg  100 B", "    with 4 of 4 of its dir's files"])
        self.assertIn("    with 0 of 4 of its dir's files", lines)

    def test_only_a_few_siblings_are_tried(self):
        relpaths = ['d/%03d' % (i,) for i in range(100)]
        src = _SizedTree('/src', {relpath: 1 for relpath in relpaths})
        dst = _SizedTree('/dst', {'e/000': 1})
        lines = _previews(relpaths, src, dst).previews['d/000']
        self.assertIn("    with 0 of %d of its dir's files" % (elsewhere.SIBLINGS_TRIED,), lines)

    def test_dates_taken_make_a_match_likelier_and_are_shown(self):
        src = _SizedTree('/src', {'x.jpg': 10}, {'x.jpg': '2024-07-01 14:03:22'})
        dst = _SizedTree('/dst', {'a/x.jpg': 20, 'b/x.jpg': 30},
                         {'a/x.jpg': '2020-01-01 00:00:00', 'b/x.jpg': '2024-07-01 14:03:22'})
        lines = _previews(['x.jpg'], src, dst).previews['x.jpg']
        self.assertEqual(lines[0], "This one: 10 B, taken 2024-07-01 14:03:22")
        self.assertEqual(lines[2:5], ["  b/", "    x.jpg  30 B", "    taken 2024-07-01 14:03:22, the same"])

    def test_a_file_without_matches_has_its_date_unread(self):
        src = _SizedTree('/src', {'x.jpg': 10})
        _previews(['x.jpg'], src, _SizedTree('/dst', {}))
        self.assertEqual(src.dates_read, [])


class SureMatchTest(unittest.TestCase):
    def sure(self, src_sizes, dst_sizes, src_dates=None, dst_dates=None):
        src = _SizedTree('/src', src_sizes, src_dates)
        return elsewhere.sure_matches(sorted(src_sizes), src,
                                      elsewhere.Index(_SizedTree('/dst', dst_sizes, dst_dates)))

    def test_the_only_one_of_the_same_size(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5, 'b/x': 6}), {'x': 'a/x'})

    def test_none_of_the_same_size_isnt_sure(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 6}), {})

    def test_two_of_the_same_size_arent_sure_unless_one_has_more_siblings(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5, 'b/x': 5}), {})
        self.assertEqual(self.sure({'d/x': 5, 'd/y': 1}, {'a/x': 5, 'b/x': 5, 'b/y': 7}),
                         {'d/x': 'b/x'})

    def test_another_date_taken_isnt_sure(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5}, {'x': '2024-01-01 00:00:00'},
                                   {'a/x': '2023-01-01 00:00:00'}), {})
        # Unknown on one side: the size decides
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5}, {'x': '2024-01-01 00:00:00'}), {'x': 'a/x'})


class IndexTest(unittest.TestCase):
    def test_built_once_then_kept_up_to_date(self):
        dst = _SizedTree('/dst', {'a/x': 1})
        index = elsewhere.Index(dst)
        self.assertFalse(index.is_built())
        index.build()
        dst.add_file_by_relpath('b/x')
        index.build()
        self.assertEqual(index.files_named('x'), {'a/x': 1})
        index.add('c/x', 3)
        index.move('a/x', 'd/x')
        index.remove('c/x')
        self.assertEqual(index.files_named('x'), {'d/x': 1})
        self.assertEqual(index.names_in('d'), {'x'})
        self.assertEqual(index.names_in('a'), set())
        index.invalidate()
        index.build()
        self.assertEqual(sorted(index.files_named('x')), ['a/x', 'b/x'])

    def test_changes_before_its_built_are_in_once_it_is(self):
        dst = _SizedTree('/dst', {})
        index = elsewhere.Index(dst)
        index.add('x', 1)
        dst.add_file_by_relpath('y')
        index.build()
        self.assertEqual(index.files_named('y'), {'y': None})

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
