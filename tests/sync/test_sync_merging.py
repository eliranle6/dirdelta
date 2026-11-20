"""Merging a text file that differs: its two versions merged (ui/merging.py), the merge written to both
replicas; and the merge's blocks and conflict marks"""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import helpers
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import merging
from dirdelta.ui import picker
from dirdelta.web import merging as web_merging
from sync_way_support import NO, Sync, YES


class MergeTest(unittest.TestCase):
    """src's notes.txt and dst's differ (src's newer); plain.bin differs too, but isn't text"""

    def setUp(self):
        self.src_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-merge-src-'))
        self.dst_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-merge-dst-'))
        self.addCleanup(shutil.rmtree, self.src_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.dst_root, ignore_errors=True)
        self.write(self.src_root, 'notes.txt', 'one\ntwo\nthree\n', 2000000000)
        self.write(self.dst_root, 'notes.txt', 'one\n2\n', 1000000000)
        self.trash = helpers.fake_trash(self)
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'), mock.patch('dirdelta.ui.messages.show')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, root, relpath, content, mtime=None):
        path = os.path.join(root, relpath)
        with open(path, 'w') as f:
            f.write(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    def read(self, root, relpath):
        with open(os.path.join(root, relpath)) as f:
            return f.read()

    def merge(self, merged, answers):
        """Check notes.txt, choose Merge, the merge being merged (or None), then answers"""
        src = localdiskdirtree.LocalReplica(self.src_root)
        dst = localdiskdirtree.LocalReplica(self.dst_root)
        self.sync = Sync(src, dst)
        picks = [['notes.txt'], None]
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)), \
                helpers.answering_option_picker(['Merge'] + answers) as self.pick_option, \
                mock.patch('dirdelta.ui.merging.merge', return_value=merged) as self.merged:
            self.sync.browse()

    def test_the_merge_is_written_to_both_once_confirmed(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.merge(['one', 'two', 'three', '2'], [YES])
        self.assertEqual(self.read(self.src_root, 'notes.txt'), 'one\ntwo\nthree\n2\n')
        self.assertEqual(self.read(self.dst_root, 'notes.txt'), 'one\ntwo\nthree\n2\n')
        # Both versions were given to merge, src's first
        args = self.merged.call_args.args
        self.assertEqual((args[2], args[3]), (['one', 'two', 'three'], ['one', '2']))

    def test_g_merges_the_selected_file_whatever_is_checked(self):
        self.write(self.src_root, 'other.txt', 'mine')
        src = localdiskdirtree.LocalReplica(self.src_root)
        dst = localdiskdirtree.LocalReplica(self.dst_root)
        self.sync = Sync(src, dst)
        # other.txt checked, notes.txt selected: g merges notes.txt, and other.txt is still checked after
        picks = [picker.Picked(Sync.MERGE_KEY, 'notes.txt', ['other.txt']), None]
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as pick_files, \
                helpers.answering_option_picker([YES]), \
                mock.patch('dirdelta.ui.merging.merge', return_value=['merged']), \
                mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.sync.browse()
        self.assertEqual(self.read(self.dst_root, 'notes.txt'), 'merged\n')
        self.assertEqual(pick_files.call_args.kwargs['picked'], ['other.txt'])

    def test_nothing_is_written_unless_confirmed_or_in_a_dry_run(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.merge(['merged'], [NO])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.merge(['merged'], [YES])
        self.assertEqual(self.read(self.src_root, 'notes.txt'), 'one\ntwo\nthree\n')
        self.assertEqual(self.read(self.dst_root, 'notes.txt'), 'one\n2\n')

    def test_going_back_from_the_merge_writes_nothing(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.merge(None, [])
        self.assertEqual(self.read(self.dst_root, 'notes.txt'), 'one\n2\n')


class BlocksTest(unittest.TestCase):
    def test_the_versions_are_alike_and_differing_blocks(self):
        self.assertEqual(merging.blocks(['a', 'b', 'c'], ['a', 'x', 'c', 'd']),
                         [('same', ['a']), ('differ', ['b'], ['x']), ('same', ['c']), ('differ', [], ['d'])])

    def test_a_differing_block_is_marked_as_git_marks_a_conflict(self):
        marked = merging.marked(('A', 'B'), ['a', 'b'], ['a', 'x'])
        self.assertEqual(marked, ['a', '<<<<<<< A', 'b', '=======', 'x', '>>>>>>> B'])
        self.assertTrue(merging.has_marks(marked))
        self.assertFalse(merging.has_marks(['a', 'b']))


class MergeScreenTest(unittest.TestCase):
    """The browser's merge window"""

    def screen(self, suggest=None):
        return web_merging.MergeScreen(1, 'Merge notes.txt', ('A', 'B'), ['a', 'b'], ['a', 'x'], None, suggest, lambda: 0)

    def test_saving_gives_the_pages_text_as_lines_and_cancel_none(self):
        screen = self.screen()
        self.assertEqual(screen.meta()['blocks'], [{'same': ['a']}, {'a': ['b'], 'b': ['x']}])
        screen.act({'action': 'save', 'text': 'a\nb\nx\n'})
        # (Its last line end isn't an empty last line)
        self.assertEqual(screen.run(), ['a', 'b', 'x'])
        screen = self.screen()
        screen.act({'action': 'cancel'})
        self.assertIsNone(screen.run())

    def asked(self, suggest):
        """The screen's AI state once it answered (it's asked on a thread of its own)"""
        screen = self.screen(suggest)
        screen.act({'action': 'suggest', 'context': 'keep B'})
        deadline = time.monotonic() + 5
        while screen.ai['status'] == 'asking' and time.monotonic() < deadline:
            time.sleep(0.01)
        return screen.state(0)['ai']

    def test_the_ais_merge_comes_in_its_state_or_why_it_failed(self):
        self.assertEqual(self.asked(lambda context: (['a', 'x'], 'took B: ' + context)),
                         {'status': 'done', 'lines': ['a', 'x'], 'notes': 'took B: keep B'})

        def fails(context):
            raise Exception("too big")
        self.assertEqual(self.asked(fails), {'status': 'failed', 'error': 'too big'})
