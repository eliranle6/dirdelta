"""The files that differ at the same paths, in a way's picker"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from sync_way_support import NO, NOTHING, SURE, Sync, YES


class DifferingTest(unittest.TestCase):
    """src and dst both have a.txt, of other sizes (src's newer), and same.txt alike; src has
    sub/b.txt too, which dst lacks"""

    def setUp(self):
        self.src_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-differ-src-'))
        self.dst_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-differ-dst-'))
        self.addCleanup(shutil.rmtree, self.src_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.dst_root, ignore_errors=True)
        helpers.make_files(self.src_root, ['a.txt', 'same.txt', 'sub/b.txt'])
        helpers.make_files(self.dst_root, ['a.txt', 'same.txt'])
        self.write(self.src_root, 'a.txt', 'the new one', 2000000000)
        self.write(self.dst_root, 'a.txt', 'old', 1000000000)
        self.trash = helpers.fake_trash(self)
        self.messages = []
        for patcher in (mock.patch('dirdelta.ui.messages.print_line',
                                   side_effect=lambda s, *a: self.messages.append(s)),
                        mock.patch('dirdelta.ui.messages.show')):
            self.show = patcher.start()
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

    def browse(self, picks, answers, only_differing=False):
        picks = list(picks)
        src = localdiskdirtree.LocalReplica(self.src_root)
        dst = localdiskdirtree.LocalReplica(self.dst_root)
        self.sync = Sync(src, dst, only_differing=only_differing)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option:
            self.sync.browse()
        return self.sync

    def offered(self):
        return [call.args[1] for call in self.pick_files.call_args_list]

    def test_the_files_that_differ_are_shown_with_the_missing_ones_and_tagged(self):
        self.browse([None], [])
        self.assertEqual(self.offered(), [['a.txt', 'sub/b.txt']])
        shown = self.pick_files.call_args.kwargs['shown_as']()
        self.assertEqual(picker.unstyled(shown['a.txt']), "a.txt  [> newer here, 11 B vs 3 B]")
        self.assertNotIn('sub/b.txt', shown)
        # Once: then only with what's sent of them again
        self.assertNotIn('a.txt', self.pick_files.call_args.kwargs['shown_as']())

    def test_their_previews_show_both_versions_and_the_missing_ones_where_dst_may_have_them(self):
        self.browse([None], [])
        sent = {}
        self.pick_files.call_args.kwargs['previews'](lambda found=None, default=None: sent.update(found or {}))
        self.assertEqual(sorted(sent), ['a.txt', 'sub/b.txt'])
        self.assertEqual(picker.unstyled(sent['a.txt'][0]), "> Another version is in %s" % (self.dst_root,))
        # The side tree goes to dst's version
        self.assertEqual(self.sync._side_follow('a.txt'), 'a.txt')

    def test_copy_replaces_dsts_version_which_goes_to_the_trash(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.browse([['a.txt', 'sub/b.txt'], None], ['Copy', YES])
        self.assertEqual(self.read(self.dst_root, 'a.txt'), 'the new one')
        self.assertEqual(self.read(self.trash, 'a.txt'), 'old')
        self.assertEqual(self.read(self.dst_root, 'sub/b.txt'), 'sub/b.txt')
        # The copy keeps its time
        self.assertEqual(os.path.getmtime(os.path.join(self.dst_root, 'a.txt')), 2000000000)
        # Both done: nothing's left
        self.assertEqual(self.offered(), [['a.txt', 'sub/b.txt']])
        header = self.pick_option.call_args_list[1].kwargs['header'].splitlines()
        self.assertEqual(header[1], "  a.txt  (replaces %s's)" % (self.dst_root,))
        self.assertIn("%s's versions of it are replaced (to the trash)." % (self.dst_root,), header)

    def test_copy_over_a_newer_version_and_copy_back_over_one_say_careful(self):
        self.write(self.dst_root, 'a.txt', 'old', 3000000000)
        self.browse([['a.txt'], ['a.txt'], None], ['Copy', NO, 'Replace', NO])
        self.assertIn("Careful: 1 file is older here than in %s, so Copy replaces a newer version." % (self.dst_root,),
                      self.pick_option.call_args_list[1].kwargs['header'].splitlines())
        self.assertNotIn("Careful", self.pick_option.call_args_list[3].kwargs['header'])
        self.write(self.dst_root, 'a.txt', 'old', 1000000000)
        self.browse([['a.txt'], ['a.txt'], None], ['Copy', NO, 'Replace', NO])
        self.assertNotIn("Careful", self.pick_option.call_args_list[1].kwargs['header'])
        self.assertIn("Careful: 1 file is newer here than in %s, so this replaces it with an older version." % (self.dst_root,),
                      self.pick_option.call_args_list[3].kwargs['header'].splitlines())

    def test_the_menu_says_which_are_replaced_and_offers_to_copy_back(self):
        self.browse([['a.txt'], None], [NOTHING])
        labels = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertIn("Copy these versions of the 1 file to %s, replacing its" % (self.dst_root,), labels)
        self.assertIn("Replace it with its version in %s" % (self.dst_root,), labels)
        self.assertIn("which %s has other versions of" % (self.dst_root,), self.pick_option.call_args.kwargs['header'])

    def test_copy_back_copies_dsts_version_over_srcs(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.browse([['a.txt'], None], ["Replace", YES])
        self.assertEqual(self.read(self.src_root, 'a.txt'), 'old')
        self.assertEqual(self.read(self.trash, 'a.txt'), 'the new one')
        self.assertEqual(self.read(self.dst_root, 'a.txt'), 'old')
        self.assertEqual(self.offered(), [['a.txt', 'sub/b.txt'], ['sub/b.txt']])
        self.assertTrue(self.sync.has_changed)

    def test_a_dry_run_copy_back_changes_nothing(self):
        self.browse([['a.txt'], None], ["Replace", YES])
        self.assertEqual(self.read(self.src_root, 'a.txt'), 'the new one')
        self.assertEqual(os.listdir(self.trash), [])

    def test_remove_removes_this_version_only(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.browse([['a.txt'], None], ['Remove', YES, SURE])
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'a.txt')))
        self.assertEqual(self.read(self.dst_root, 'a.txt'), 'old')
        self.assertEqual(self.offered(), [['a.txt', 'sub/b.txt'], ['sub/b.txt']])

    def test_a_failed_replacing_copy_keeps_dsts_version_and_the_pick(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=OSError('disk full')):
            self.browse([['a.txt'], None], ['Copy', YES])
        self.assertEqual(self.read(self.dst_root, 'a.txt'), 'old')
        self.assertEqual(self.offered()[1], ['a.txt', 'sub/b.txt'])
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['a.txt'])

    def test_only_the_files_that_differ(self):
        self.browse([None], [], only_differing=True)
        self.assertEqual(self.offered(), [['a.txt']])
        self.assertIn('other versions', self.pick_files.call_args.kwargs['header'])

    def test_no_files_that_differ_says_so(self):
        self.write(self.dst_root, 'a.txt', 'the new one')
        self.browse([], [], only_differing=True)
        self.assertEqual(self.offered(), [])
        self.assertIn("differs", self.show.call_args.args[1][0])

    def test_rename_and_ai_are_about_the_missing_ones_only(self):
        self.browse([['a.txt'], None], [NOTHING])
        shown = helpers.shown_of(self.pick_option.call_args.args[0])
        disabled = [text.text.lstrip() for text in shown.values() if isinstance(text, picker.Disabled)]
        self.assertTrue(any(text.startswith("Rename the files matching 0") for text in disabled), disabled)
        self.assertIn("[a] Ask AI what to do with it, and review its plan: can't: it's for the files %s lacks" % (self.dst_root,),
                      disabled)
        self.assertIsNone(self.sync._ask_ai(['a.txt']))
        self.assertEqual(self.show.call_args.args[0], "Nothing to ask about")


if __name__ == '__main__':
    unittest.main()
