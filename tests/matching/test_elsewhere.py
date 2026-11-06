"""Where the other replica may have a missing file: its previews, renamed files, times, sure matches"""
import os
import shutil
import tempfile
import unittest

import helpers
from dirdelta.matching import elsewhere
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from dirdelta.util import text
from elsewhere_support import Sent, SizedTree, previews_of


class FindPreviewsTest(unittest.TestCase):
    def test_a_file_the_other_replica_lacks_by_name(self):
        src = SizedTree('/src', {'a/x.jpg': 10})
        dst = SizedTree('/dst', {'b/y.jpg': 10})
        self.assertEqual(previews_of(['a/x.jpg'], src, dst).previews['a/x.jpg'],
                         ["This one: 10 B", "Same name in /dst: none"])

    def test_the_likeliest_first_by_size(self):
        src = SizedTree('/src', {'new/x.jpg': 2048})
        dst = SizedTree('/dst', {'old/2024/x.jpg': 2048, 'old/x.jpg': 100, 'x.jpg': 2000,
                                  'old/2024/other.jpg': 2048})
        self.assertEqual(previews_of(['new/x.jpg'], src, dst).previews['new/x.jpg'], [
            "This one: 2.0 KB",
            "Same name in /dst:",
            "  old/2024/",
            "    x.jpg  2.0 KB, same size",
            elsewhere.SURELY_MOVED,
            "  ./",
            "    x.jpg  2000 B",
            "  old/",
            "    x.jpg  100 B",
        ])

    def test_unknown_sizes_come_last(self):
        src = SizedTree('/src', {'x': 5})
        dst = SizedTree('/dst', {'a/x': None, 'b/x': 500})
        lines = previews_of(['x'], src, dst).previews['x']
        self.assertEqual(lines[2:], ["  b/", "    x  500 B", "  a/", "    x"])

    def test_a_common_names_matches_are_cut_keeping_the_likeliest(self):
        sizes = {'d%02d/README' % (i,): i for i in range(elsewhere.MAX_MATCHES + 3)}
        sizes['z/README'] = 1000
        src = SizedTree('/src', {'README': 1000})
        lines = previews_of(['README'], src, SizedTree('/dst', sizes)).previews['README']
        self.assertEqual(lines[2:5], ["  z/", "    README  1000 B, same size", elsewhere.SURELY_MOVED])
        self.assertEqual(lines[-1], "(and 4 more)")
        self.assertEqual(sum(1 for line in lines if line.startswith('    README')), elsewhere.MAX_MATCHES)

    def test_says_how_far_it_got_then_nothing_for_the_rest(self):
        src = SizedTree('/src', {'a': 1, 'b': 1})
        sent = previews_of(['a', 'b'], src, SizedTree('/dst', {}))
        self.assertEqual(sent.defaults[0][-1], "Listing its files")
        self.assertEqual(sent.defaults[-1], [])
        self.assertEqual(sorted(sent.previews), ['a', 'b'])

    def test_stops_when_the_picker_is_gone(self):
        def send(found=None, default=None):
            raise picker.PickerClosed()
        with self.assertRaises(picker.PickerClosed):
            elsewhere.find_previews(['a'], SizedTree('/src', {}), elsewhere.Index(SizedTree('/dst', {})),
                                    send)

    def test_a_local_dir_is_found_by_find_with_sizes(self):
        root = tempfile.mkdtemp(prefix='dirdelta-elsewhere-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['dst/moved/x.txt', 'src/x.txt'])
        src = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'src'), True)
        # Not scanned, as for a dirdiff
        dst = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'dst'), True)
        lines = previews_of(['x.txt'], src, dst).previews['x.txt']
        self.assertEqual(lines[0], "This one: 9 B")
        self.assertIn("Same name in %s:" % (dst.displayname(),), lines)
        self.assertEqual(lines[lines.index("  moved/") + 1], "    x.txt  15 B")

    def test_siblings_in_a_matchs_dir_make_it_likelier(self):
        # photos/ was moved to old/photos/; other/ has one of its names, of a different size
        src = SizedTree('/src', {'photos/%d.jpg' % (i,): i for i in range(5)})
        dst = SizedTree('/dst', dict({'old/photos/%d.jpg' % (i,): 100 + i for i in range(5)},
                                      **{'other/0.jpg': 50}))
        sent = previews_of(sorted(src._sizes), src, dst)
        lines = sent.previews['photos/0.jpg']
        self.assertEqual(lines[2:5], ["  old/photos/", "    0.jpg  100 B", "    with 4 of 4 of its dir's files"])
        self.assertIn("    with 0 of 4 of its dir's files", lines)

    def test_dates_taken_make_a_match_likelier_and_are_shown(self):
        src = SizedTree('/src', {'x.jpg': 10}, {'x.jpg': '2024-07-01 14:03:22'})
        dst = SizedTree('/dst', {'a/x.jpg': 20, 'b/x.jpg': 30},
                         {'a/x.jpg': '2020-01-01 00:00:00', 'b/x.jpg': '2024-07-01 14:03:22'})
        lines = previews_of(['x.jpg'], src, dst).previews['x.jpg']
        self.assertEqual(lines[0], "This one: 10 B, taken 2024-07-01 14:03:22")
        self.assertEqual(lines[2:5], ["  b/", "    x.jpg  30 B", "    taken 2024-07-01 14:03:22, the same"])


class RenamedTest(unittest.TestCase):
    """src's big.mov, which dst has as clip.mov (another name, the same size)"""
    BIG = elsewhere.RENAMED_MIN_SIZE

    def setUp(self):
        self.src = SizedTree('/src', {'big.mov': self.BIG, 'small.txt': 10}, hashes={'big.mov': 'H'})
        self.dst = SizedTree('/dst', {'v/clip.mov': self.BIG, 'v/other.mov': self.BIG, 'w/note.txt': 10},
                              hashes={'v/clip.mov': 'H', 'v/other.mov': 'X'})
        self.index = elsewhere.Index(self.dst)
        self.checked = {}

    def lines(self, relpath):
        sent = Sent()
        elsewhere.find_previews(['big.mov', 'small.txt'], self.src, self.index, sent, self.checked)
        return sent.previews[relpath]

    def test_big_files_of_its_size_are_candidates_too(self):
        lines = self.lines('big.mov')
        self.assertIn("Same name in /dst: none", lines)
        section = lines[lines.index("Same size, other name:"):]
        self.assertEqual(section[1:3], ["  v/", "    clip.mov  64.0 KB, same size"])
        self.assertIn("    other.mov  64.0 KB, same size", section)
        # Not sure until their contents are compared
        self.assertNotIn(elsewhere.SURELY_RENAMED, lines)
        # Small files' sizes are too common
        self.assertNotIn("Same size, other name:", self.lines('small.txt'))

    def test_the_same_contents_make_it_surely_renamed_and_drop_the_others(self):
        self.index.build()
        elsewhere.check_all(['big.mov'], self.src, elsewhere.Index(self.src), self.index, self.checked)
        lines = self.lines('big.mov')
        self.assertNotIn("    other.mov  64.0 KB, same size", lines)
        self.assertEqual(lines[-2:], ["    the same contents", elsewhere.SURELY_RENAMED])
        self.assertEqual(elsewhere.sure_matches(['big.mov'], self.src, self.index, self.checked),
                         {'big.mov': 'v/clip.mov'})

    def test_other_contents_drop_a_renamed_one(self):
        self.dst._hashes['v/clip.mov'] = 'X'
        self.index.build()
        elsewhere.check_all(['big.mov'], self.src, elsewhere.Index(self.src), self.index, self.checked)
        self.assertNotIn("Same size, other name:", self.lines('big.mov'))

    def test_what_may_be_elsewhere_and_whats_left_to_compare(self):
        # dst knows its hashes (as Drive does), so small.txt may be there too, renamed
        self.assertEqual(elsewhere.may_be_elsewhere(['big.mov', 'small.txt'], self.src, self.index),
                         ['big.mov', 'small.txt'])
        progress = []
        elsewhere.check_all(['big.mov', 'small.txt'], self.src, elsewhere.Index(self.src), self.index,
                            self.checked, lambda *args: progress.append(args))
        self.assertEqual(progress, [(1, 2, 'big.mov'), (2, 2, 'small.txt')])
        self.assertEqual(elsewhere.to_check(['big.mov', 'small.txt'], self.src, self.index, self.checked), [])
        self.assertEqual(elsewhere.may_be_elsewhere(['big.mov', 'small.txt'], self.src, self.index, self.checked),
                         ['big.mov'])

    def test_a_file_of_another_name_and_size_is_found_by_its_hash(self):
        self.src._hashes['small.txt'] = 'S'
        self.dst._sizes['w/renamed.txt'] = 10
        self.dst._hashes['w/renamed.txt'] = 'S'
        self.dst.add_file_by_relpath('w/renamed.txt')
        elsewhere.check_all(['small.txt'], self.src, elsewhere.Index(self.src), self.index, self.checked)
        self.assertEqual(self.checked['small.txt'], {'w/renamed.txt': True})
        lines = self.lines('small.txt')
        self.assertIn("    renamed.txt  10 B, same size", lines)
        self.assertEqual(lines[-1], elsewhere.SURELY_RENAMED)

    def test_the_index_by_size_is_kept_up_to_date(self):
        self.index.build()
        self.index.move('v/clip.mov', 'x/clip.mov')
        self.index.add('y/new.mov', self.BIG)
        self.index.remove('v/other.mov')
        self.assertEqual(self.index.files_sized(self.BIG), {'x/clip.mov', 'y/new.mov'})
        self.assertEqual(self.index.files_sized(10), set())


class ModifiedTimeTest(unittest.TestCase):
    def test_modification_times_are_shown_and_make_a_match_likelier(self):
        src = SizedTree('/src', {'x': 5}, times={'x': 1000})
        dst = SizedTree('/dst', {'a/x': 5, 'b/x': 5, 'c/x': 5}, times={'a/x': 5000, 'b/x': 1001, 'c/x': 10})
        lines = previews_of(['x'], src, dst).previews['x']
        self.assertEqual(lines[1], "  modified " + elsewhere.preview_lines._format_time(1000))
        # The same time (within SAME_TIME) first, then the others by path
        self.assertEqual(lines[3:5], ["  b/", "    x  5 B, same size"])
        self.assertIn("    modified %s, the same" % (elsewhere.preview_lines._format_time(1001),), lines)
        self.assertIn("    modified %s, newer" % (elsewhere.preview_lines._format_time(5000),), lines)
        self.assertIn("    modified %s, older" % (elsewhere.preview_lines._format_time(10),), lines)


class SureMatchTest(unittest.TestCase):
    def sure(self, src_sizes, dst_sizes, src_dates=None, dst_dates=None):
        src = SizedTree('/src', src_sizes, src_dates)
        return elsewhere.sure_matches(sorted(src_sizes), src,
                                      elsewhere.Index(SizedTree('/dst', dst_sizes, dst_dates)))

    def test_the_only_one_of_the_same_size(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5, 'b/x': 6}), {'x': 'a/x'})

    def test_two_of_the_same_size_arent_sure_unless_one_has_more_siblings(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5, 'b/x': 5}), {})
        self.assertEqual(self.sure({'d/x': 5, 'd/y': 1}, {'a/x': 5, 'b/x': 5, 'b/y': 7}),
                         {'d/x': 'b/x'})

    def test_another_date_taken_isnt_sure(self):
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5}, {'x': '2024-01-01 00:00:00'},
                                   {'a/x': '2023-01-01 00:00:00'}), {})
        # Unknown on one side: the size decides
        self.assertEqual(self.sure({'x': 5}, {'a/x': 5}, {'x': '2024-01-01 00:00:00'}), {'x': 'a/x'})


class FormatSizeTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(text.format_size(0), "0 B")
        self.assertEqual(text.format_size(1023), "1023 B")
        self.assertEqual(text.format_size(1536), "1.5 KB")
        self.assertEqual(text.format_size(3 * 1024 ** 2), "3.0 MB")
        self.assertEqual(text.format_size(5 * 1024 ** 4), "5120.0 GB")


if __name__ == '__main__':
    unittest.main()
