"""Comparing contents, and the hashes the hashing jobs found"""
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta.hashes import hashing
from dirdelta.matching import elsewhere
from dirdelta.trees import dirtree
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from elsewhere_support import ScriptedSelection, Sent, SizedTree


class CheckContentsTest(unittest.TestCase):
    """src's x has matches a/x and b/x of its size, and c/x of another"""
    def setUp(self):
        self.src = SizedTree('/src', {'x': 5, 'y': 5, 'd/z': 1}, hashes={'x': 'H', 'y': 'Y'})
        self.dst = SizedTree('/dst', {'a/x': 5, 'b/x': 5, 'c/x': 6, 'e/y': 5},
                              hashes={'a/x': 'H', 'b/x': 'other', 'c/x': 'C', 'e/y': None})
        self.index = elsewhere.Index(self.dst)
        self.index.build()
        self.checked = {}
        self.sent = Sent()

    def check(self, moves, at=None):
        with self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(sorted(self.src._sizes), self.src, elsewhere.Index(self.src),
                                     self.index, self.checked, ScriptedSelection(moves, at), self.sent)

    def test_the_same_contents_are_it_and_the_others_are_dropped(self):
        self.check(['x'])
        # The ones of its size are compared, and its hash looked up in dst's
        self.assertEqual(self.checked, {'x': {'a/x': True, 'b/x': False}})
        lines = self.sent.previews['x']
        # Its hash, known without reading it (as Drive's are)
        self.assertEqual(lines[1], "  SHA-256 H")
        self.assertEqual(lines[3:], ["  a/", "    x  5 B, same size", "    with 0 of 1 of its dir's files",
                                     "    the same contents", elsewhere.SURELY_MOVED])

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

        class Selection(ScriptedSelection):
            def wait_next(self_, timeout=None):
                if self_._last is not None:
                    # Built meanwhile (by the previews' thread)
                    index.build()
                return ScriptedSelection.wait_next(self_, timeout)
        with self.assertRaises(picker.PickerClosed):
            elsewhere.check_contents(['x'], self.src, elsewhere.Index(self.src), self.index,
                                     self.checked, Selection(['x', None]), self.sent)
        self.assertIn('x', self.checked)

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
                                     ScriptedSelection(['x']), self.sent)
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
                                     ScriptedSelection(['x']), self.sent)
        self.assertEqual(self.checked, {'x': {'a/x': True}})
        # Drive's hashes, read when its index was built: none asked for again
        self.assertEqual(sorted(call.args[1] for call in dst.content_hash.call_args_list), ['sha1', 'sha256'])


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
            self.addCleanup(hashing.registry._jobs.pop, job.root, None)
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
        sent = Sent()
        # Then it'd go on sending them as files are hashed, until the picker is gone
        with mock.patch('dirdelta.matching.elsewhere.previews.time.sleep', side_effect=picker.PickerClosed), \
                self.assertRaises(picker.PickerClosed):
            elsewhere.find_previews(['small.txt'], self.src, self.dst_index, sent,
                                    src_index=elsewhere.Index(self.src))
        self.assertIn("  contents not hashed yet (src: 0% hashed (0/2, not hashing))", sent.previews['small.txt'])
        self.hash('src')
        sent = Sent()
        with mock.patch('dirdelta.matching.elsewhere.previews.time.sleep', side_effect=picker.PickerClosed):
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
        with mock.patch('dirdelta.matching.elsewhere.previews.time.sleep', side_effect=sleep), \
                self.assertRaises(picker.PickerClosed):
            elsewhere.find_previews(['small.txt', 'other.txt'], self.src, self.dst_index,
                                    lambda found=None, default=None: sends.append(dict(found or {})),
                                    src_index=self.src_index)
        again = sends[-1]
        self.assertEqual(sorted(again), ['other.txt', 'small.txt'])
        self.assertIn(elsewhere.SURELY_RENAMED, again['small.txt'])


if __name__ == '__main__':
    unittest.main()
