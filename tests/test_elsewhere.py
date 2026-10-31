import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import dirtree
from dirdelta import elsewhere
from dirdelta import hashing
from dirdelta import localdiskdirtree
from dirdelta import picker
import helpers


class _SizedTree(dirtree.DirTree):
    """A DirTree whose files have the given sizes (and dates taken)"""
    def __init__(self, rootpath, sizes, dates=None, hashes=None, times=None):
        super(_SizedTree, self).__init__(rootpath)
        self._sizes = sizes
        self._dates = dates or {}
        self._hashes = hashes or {}
        self._times = times or {}
        # The files whose hashes aren't known without working them out (unlike Drive's)
        self.slow = set()
        self.dates_read = []
        self.hashed = []
        for relpath in sizes:
            self.add_file_by_relpath(relpath)

    def file_size(self, relpath):
        return self._sizes.get(relpath)

    def date_taken(self, relpath):
        self.dates_read.append(relpath)
        return self._dates.get(relpath)

    def content_hash(self, relpath, algorithm, should_stop=None):
        # Like Drive's: SHA-256s known. As if working it out took a while: asked once whether to stop.
        if should_stop is not None and should_stop():
            raise dirtree.HashStopped()
        self.hashed.append(relpath)
        return self._hashes.get(relpath) if algorithm == 'sha256' else None

    def known_hashes(self, relpath):
        return ('sha256',) if self._hashes.get(relpath) and relpath not in self.slow else ()

    def modified_time(self, relpath):
        return self._times.get(relpath)


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
            elsewhere.SURELY_MOVED,
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
        self.assertEqual(lines[2:5], ["  z/", "    README  1000 B, same size", elsewhere.SURELY_MOVED])
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
        lines = _previews(['x.txt'], src, dst).previews['x.txt']
        self.assertEqual(lines[0], "This one: 9 B")
        self.assertIn("In %s, likeliest first:" % (dst.displayname(),), lines)
        self.assertEqual(lines[lines.index("  moved/") + 1], "    x.txt  15 B")

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


class RenamedTest(unittest.TestCase):
    """src's big.mov, which dst has as clip.mov (another name, the same size)"""
    BIG = elsewhere.RENAMED_MIN_SIZE

    def setUp(self):
        self.src = _SizedTree('/src', {'big.mov': self.BIG, 'small.txt': 10}, hashes={'big.mov': 'H'})
        self.dst = _SizedTree('/dst', {'v/clip.mov': self.BIG, 'v/other.mov': self.BIG, 'w/note.txt': 10},
                              hashes={'v/clip.mov': 'H', 'v/other.mov': 'X'})
        self.index = elsewhere.Index(self.dst)
        self.checked = {}

    def lines(self, relpath):
        sent = _Sent()
        elsewhere.find_previews(['big.mov', 'small.txt'], self.src, self.index, sent, self.checked)
        return sent.previews[relpath]

    def test_big_files_of_its_size_are_candidates_too(self):
        lines = self.lines('big.mov')
        self.assertIn("  no file of this name", lines)
        section = lines[lines.index("Of its size, another name:"):]
        self.assertEqual(section[1:3], ["  v/", "    clip.mov  64.0 KB, same size"])
        self.assertIn("    other.mov  64.0 KB, same size", section)
        # Not sure until their contents are compared
        self.assertNotIn(elsewhere.SURELY_RENAMED, lines)
        # Small files' sizes are too common
        self.assertNotIn("Of its size, another name:", self.lines('small.txt'))

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
        self.assertNotIn("Of its size, another name:", self.lines('big.mov'))

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
        src = _SizedTree('/src', {'x': 5}, times={'x': 1000})
        dst = _SizedTree('/dst', {'a/x': 5, 'b/x': 5, 'c/x': 5}, times={'a/x': 5000, 'b/x': 1001, 'c/x': 10})
        lines = _previews(['x'], src, dst).previews['x']
        self.assertEqual(lines[1], "  modified " + elsewhere._format_time(1000))
        # The same time (within SAME_TIME) first, then the others by path
        self.assertEqual(lines[3:5], ["  b/", "    x  5 B, same size"])
        self.assertIn("    modified %s, the same" % (elsewhere._format_time(1001),), lines)
        self.assertIn("    modified %s, newer" % (elsewhere._format_time(5000),), lines)
        self.assertIn("    modified %s, older" % (elsewhere._format_time(10),), lines)


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

    def test_a_hash_is_worked_out_once_and_moves_with_its_file(self):
        dst = _SizedTree('/dst', {'a/x': 1}, hashes={'a/x': 'H'})
        index = elsewhere.Index(dst)
        index.build()
        self.assertEqual(index.content_hash('a/x', 'sha256'), 'H')
        self.assertEqual(index.content_hash('a/x', 'sha256'), 'H')
        self.assertEqual(dst.hashed, ['a/x'])
        index.move('a/x', 'b/x')
        self.assertEqual(index.content_hash('b/x', 'sha256'), 'H')
        self.assertEqual(dst.hashed, ['a/x'])
        index.remove('b/x')
        self.assertIsNone(index.content_hash('b/x', 'sha256'))

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


class _Selection(object):
    """A picker.Selection that moves to each of moves in turn (None: a wait that times out), then
    the picker is gone; at, if given, says where it is when asked (else at the last move)"""
    def __init__(self, moves, at=None):
        self._moves = list(moves)
        self._at = at
        self._last = None

    def wait_next(self, timeout=None):
        if not self._moves:
            raise picker.PickerClosed()
        move = self._moves.pop(0)
        if move is not None:
            self._last = move
        return move

    def is_at(self, relpath):
        return (self._at(relpath) if self._at is not None else self._last == relpath)


class CheckContentsTest(unittest.TestCase):
    """src's x has matches a/x and b/x of its size, and c/x of another"""
    def setUp(self):
        self.src = _SizedTree('/src', {'x': 5, 'y': 5, 'd/z': 1}, hashes={'x': 'H', 'y': 'Y'})
        self.dst = _SizedTree('/dst', {'a/x': 5, 'b/x': 5, 'c/x': 6, 'e/y': 5},
                              hashes={'a/x': 'H', 'b/x': 'other', 'c/x': 'C', 'e/y': None})
        self.index = elsewhere.Index(self.dst)
        self.index.build()
        self.checked = {}
        self.sent = _Sent()

    def check(self, moves, at=None):
        with self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(sorted(self.src._sizes), self.src, elsewhere.Index(self.src),
                                     self.index, self.checked, _Selection(moves, at), self.sent)

    def test_the_surely_line_is_highlighted(self):
        self.assertEqual(elsewhere.SURELY_MOVED, picker.highlighted("\u2192 surely this file, moved"))
        self.assertTrue(elsewhere.SURELY_MOVED.startswith(picker.HIGHLIGHT_MARK + 'green' + picker.HIGHLIGHT_MARK))

    def test_the_same_contents_are_it_and_the_others_are_dropped(self):
        self.check(['x'])
        # The ones of its size are compared, and its hash looked up in dst's
        self.assertEqual(self.checked, {'x': {'a/x': True, 'b/x': False}})
        lines = self.sent.previews['x']
        # Its hash, known without reading it (as Drive's are)
        self.assertEqual(lines[1], "  SHA-256 H")
        self.assertEqual(lines[3:], ["  a/", "    x  5 B, same size", "    with 0 of 1 of its dir's files",
                                     "    the same contents", elsewhere.SURELY_MOVED])

    def test_it_says_its_comparing_meanwhile(self):
        sends = []
        self.sent = lambda found=None, default=None: sends.append(dict(found))
        self.check(['x'])
        self.assertEqual(sends[0]['x'][-2:], ["Comparing its contents with the",
                                              "2 files of its size and /dst's by hash..."])

    def test_other_contents_are_said_and_arent_sure(self):
        self.dst._hashes['a/x'] = 'other'
        self.index.invalidate()
        self.index.build()
        self.check(['x'])
        lines = self.sent.previews['x']
        self.assertEqual(lines.count("    other contents"), 2)
        self.assertNotIn(elsewhere.SURELY_MOVED, lines)
        self.assertEqual(elsewhere.sure_matches(['x'], self.src, self.index, self.checked), {})

    def test_unknown_hashes_arent_compared(self):
        self.check(['y'])
        self.assertEqual(self.checked, {'y': {}})
        self.assertNotIn("    other contents", self.sent.previews['y'])

    def test_each_file_once_and_only_files_with_matches_of_its_size(self):
        self.check(['x', 'd', 'd/z', 'x'])
        # Once each (dst's, Drive-like, when its index was built)
        self.assertEqual(self.src.hashed.count('x'), 1)
        self.assertEqual(sorted(self.dst.hashed), ['a/x', 'b/x', 'c/x'])
        # Each selected file's preview is sent at once, compared or not
        self.assertEqual(sorted(self.sent.previews), ['d/z', 'x'])

    def test_moving_on_stops_it_and_goes_on_where_the_selection_is(self):
        # While x is hashed (it takes a while: it isn't known), the selection moves to y
        self.src.slow.add('x')
        self.check(['x', 'y'], at=lambda relpath: relpath == 'y')
        self.assertNotIn('x', self.checked)
        self.assertIn('y', self.checked)

    def test_it_waits_for_the_index(self):
        self.index.invalidate()
        index = self.index

        class Selection(_Selection):
            def wait_next(self_, timeout=None):
                if self_._last is not None:
                    # Built meanwhile (by the previews' thread)
                    index.build()
                return _Selection.wait_next(self_, timeout)
        with self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(['x'], self.src, elsewhere.Index(self.src), self.index,
                                     self.checked, Selection(['x', None]), self.sent)
        self.assertIn('x', self.checked)

    def test_hashes_are_kept_in_the_indexes(self):
        src_index = elsewhere.Index(self.src)
        with self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(['x', 'y'], self.src, src_index, self.index, self.checked,
                                     _Selection(['x']), self.sent)
        self.assertEqual(self.index.content_hash('a/x', 'sha256'), 'H')
        self.assertEqual(src_index.content_hash('x', 'sha256'), 'H')
        self.assertEqual(self.src.hashed.count('x'), 1)

    def test_two_local_files_are_compared_up_to_where_they_differ(self):
        root = tempfile.mkdtemp(prefix='dirdelta-elsewhere-')
        self.addCleanup(shutil.rmtree, root)
        for relpath, contents in (('src/x', b'same'), ('dst/a/x', b'same'), ('dst/b/x', b'diff')):
            os.makedirs(os.path.dirname(os.path.join(root, relpath)), exist_ok=True)
            with open(os.path.join(root, relpath), 'wb') as f:
                f.write(contents)
        src = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'src'), True)
        index = elsewhere.Index(localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'dst'), True))
        index.build()
        with mock.patch.object(localdiskdirtree.LocalDiskDirTree, 'content_hash') as content_hash, \
                self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(['x'], src, elsewhere.Index(src), index, self.checked,
                                     _Selection(['x']), self.sent)
        self.assertEqual(self.checked, {'x': {'a/x': True, 'b/x': False}})
        content_hash.assert_not_called()

    def test_a_local_file_and_a_drive_one_by_drives_fastest_hash(self):
        root = tempfile.mkdtemp(prefix='dirdelta-elsewhere-')
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, 'src'))
        with open(os.path.join(root, 'src', 'x'), 'wb') as f:
            f.write(b'same')
        src = localdiskdirtree.LocalDiskDirTree(os.path.join(root, 'src'), True)
        dst = mock.Mock(spec=dirtree.DirTree)
        dst.displayname.return_value = 'cloud/d'
        dst.files_by_name.return_value = {'x': [('a/x', 4)]}
        dst.date_taken.return_value = None
        dst.local_path.return_value = None
        dst.modified_time.return_value = None
        # Drive has both: SHA-1 is the faster to work out
        dst.known_hashes.return_value = ('sha1', 'sha256')
        dst.content_hash.side_effect = lambda relpath, algorithm, should_stop=None: \
            {'sha1': hashlib.sha1(b'same').hexdigest(), 'sha256': 'unused'}[algorithm]
        index = elsewhere.Index(dst)
        index.build()
        with self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(['x'], src, elsewhere.Index(src), index, self.checked,
                                     _Selection(['x']), self.sent)
        self.assertEqual(self.checked, {'x': {'a/x': True}})
        # Drive's hashes, read when its index was built: none asked for again
        self.assertEqual(sorted(call.args[1] for call in dst.content_hash.call_args_list), ['sha1', 'sha256'])


class FormatSizeTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(elsewhere.format_size(0), "0 B")
        self.assertEqual(elsewhere.format_size(1023), "1023 B")
        self.assertEqual(elsewhere.format_size(1536), "1.5 KB")
        self.assertEqual(elsewhere.format_size(3 * 1024 ** 2), "3.0 MB")
        self.assertEqual(elsewhere.format_size(5 * 1024 ** 4), "5120.0 GB")



class HashedReplicasTest(unittest.TestCase):
    """Two local replicas hashed by their jobs (hashing.py): src's small.txt is dst's renamed.dat,
    too small to be a candidate by its size"""
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-elsewhere-hashed-'))
        self.addCleanup(shutil.rmtree, self.root)
        for relpath, contents in (('src/small.txt', 'same'), ('src/other.txt', 'mine'),
                                  ('dst/d/renamed.dat', 'same'), ('dst/d/other.txt', 'xxxx')):
            path = os.path.join(self.root, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write(contents)
        self.src = localdiskdirtree.LocalDiskDirTree(os.path.join(self.root, 'src'), True)
        self.dst = localdiskdirtree.LocalDiskDirTree(os.path.join(self.root, 'dst'), True)
        self.jobs = {}
        for name in ('src', 'dst'):
            job = hashing.job(os.path.join(self.root, name))
            self.addCleanup(hashing._jobs.pop, job.root, None)
            self.jobs[name] = job
        self.src_index, self.dst_index = elsewhere.Index(self.src), elsewhere.Index(self.dst)

    def hash(self, *names):
        """The replicas hashed, as their jobs would (here, at once)"""
        for name in names:
            job = self.jobs[name]
            job.scan()
            # Started, without the pool's workers
            job._is_started = True
            for relpath in job.files():
                job._hash(relpath) if job._take(relpath) else None

    def test_a_renamed_file_of_any_size_is_found_by_its_hash(self):
        self.hash('src', 'dst')
        self.dst_index.build()
        self.assertEqual(elsewhere.known_same('small.txt', self.src_index, self.dst_index),
                         {'d/renamed.dat': True})
        self.assertEqual(elsewhere.sure_matches(['small.txt'], self.src, self.dst_index, {}, self.src_index),
                         {'small.txt': 'd/renamed.dat'})
        # Without the jobs' hashes it's only a file too small to say
        self.assertEqual(elsewhere.sure_matches(['small.txt'], self.src, elsewhere.Index(self.dst), {}), {})

    def test_other_contents_by_the_hashes_known(self):
        self.hash('src', 'dst')
        self.dst_index.build()
        self.assertEqual(elsewhere.known_same('other.txt', self.src_index, self.dst_index, ['d/other.txt']),
                         {'d/other.txt': False})

    def test_hashes_come_into_the_index_as_theyre_hashed(self):
        self.jobs['dst'].scan()
        self.dst_index.build()
        self.assertEqual(self.dst_index.hash_algorithms(), [])
        self.assertEqual(self.dst_index.hash_coverage('sha1'), 0)
        self.jobs['dst'].subscribe(lambda relpath, hashes: None)
        self.hash('dst')
        self.assertEqual(self.dst_index.hash_algorithms(), ['sha1'])
        self.assertEqual(self.dst_index.files_hashed('sha1', hashlib.sha1(b'same').hexdigest()),
                         {'d/renamed.dat'})
        self.assertEqual(self.dst_index.hash_coverage('sha1'), 1)
        self.assertEqual(self.dst_index.take_new(), {'d/renamed.dat', 'd/other.txt'})
        self.assertEqual(self.dst_index.take_new(), set())

    def test_an_excluded_dirs_hashes_arent_in(self):
        index = elsewhere.Index(self.dst, excluded='d')
        self.hash('dst')
        self.assertEqual(index.hash_algorithms(), [])

    def test_its_preview_says_its_hash_or_that_it_isnt_hashed_yet(self):
        self.jobs['src'].scan()
        self.hash('dst')
        sent = _Sent()
        # Then it'd go on sending them as files are hashed, until the picker is gone
        with mock.patch('dirdelta.elsewhere.time.sleep', side_effect=picker.PickerClosed), \
                self.assertRaises(picker.PickerClosed):
            elsewhere.find_previews(['small.txt'], self.src, self.dst_index, sent,
                                    src_index=elsewhere.Index(self.src))
        self.assertIn("  contents not hashed yet (src: 0% hashed (not hashing))", sent.previews['small.txt'])
        self.hash('src')
        sent = _Sent()
        with mock.patch('dirdelta.elsewhere.time.sleep', side_effect=picker.PickerClosed):
            with self.assertRaises(picker.PickerClosed):
                elsewhere.find_previews(['other.txt'], self.src, self.dst_index, sent, src_index=self.src_index)
        lines = sent.previews['other.txt']
        self.assertIn("  SHA-1 " + hashlib.sha1(b'mine').hexdigest()[:16], lines)
        self.assertIn("  no file in %s has its contents" % (self.dst.displayname(),), lines)

    def test_previews_are_sent_again_as_files_are_hashed(self):
        self.jobs['src'].scan()
        self.jobs['dst'].scan()
        sends = []
        hashed = []

        def sleep(seconds):
            # Meanwhile, the jobs hash their files; then the picker is gone
            if hashed:
                raise picker.PickerClosed()
            hashed.append(True)
            self.hash('src', 'dst')
        with mock.patch('dirdelta.elsewhere.time.sleep', side_effect=sleep), \
                self.assertRaises(picker.PickerClosed):
            elsewhere.find_previews(['small.txt', 'other.txt'], self.src, self.dst_index,
                                    lambda found=None, default=None: sends.append(dict(found or {})),
                                    src_index=self.src_index)
        again = sends[-1]
        self.assertEqual(sorted(again), ['other.txt', 'small.txt'])
        self.assertIn(elsewhere.SURELY_RENAMED, again['small.txt'])


if __name__ == '__main__':
    unittest.main()
