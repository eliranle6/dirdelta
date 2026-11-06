"""Renaming files to where the other replica has them"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.matching import elsewhere
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from sync_way_support import NOTHING, Sync, YES


class RenameTest(unittest.TestCase):
    """src has photos/x.jpg, which dst has at old/x.jpg (the same size): moved there; and
    photos/y.jpg, which dst lacks"""

    def setUp(self):
        self.src_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-rename-src-'))
        self.dst_root = os.path.realpath(tempfile.mkdtemp(prefix='dirstuff-rename-dst-'))
        for root, relpath in ((self.src_root, 'photos/x.jpg'), (self.dst_root, 'old/x.jpg'),
                              (self.src_root, 'photos/y.jpg')):
            os.makedirs(os.path.dirname(os.path.join(root, relpath)), exist_ok=True)
            with open(os.path.join(root, relpath), 'w') as f:
                f.write('the photo')
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'), mock.patch('dirdelta.ui.messages.show')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.src_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.dst_root, ignore_errors=True)

    def browse(self, answers, is_dry_run=False):
        self.src = localdiskdirtree.LocalDiskDirTree(self.src_root, True)
        self.dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, True)
        self.dst_index = elsewhere.Index(self.dst)
        self.src_index = elsewhere.Index(self.src)
        self.src_index.build()
        picks = [['photos/x.jpg', 'photos/y.jpg'], None]
        sync = Sync(self.src, self.dst, src_index=self.src_index, dst_index=self.dst_index)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option, \
                mock.patch('dirdelta.util.dryrun.DRYRUN', is_dry_run):
            sync.browse()
        return sync

    def test_rename_in_dst_moves_its_match_to_the_files_path(self):
        sync = self.browse(['Rename the', YES])
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'photos/x.jpg')))
        # Its dir, left empty, is gone too
        self.assertFalse(os.path.exists(os.path.join(self.dst_root, 'old')))
        self.assertEqual(self.dst_index.files_named('x.jpg'), {'photos/x.jpg': 9})
        self.assertTrue(sync.has_changed)
        # Only y.jpg is left, still picked (x.jpg was done)
        self.assertEqual(self.pick_files.call_args.args[1], ['photos/y.jpg'])
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['photos/y.jpg'])
        header = self.pick_option.call_args.kwargs['header'].splitlines()
        # old/ has only it: moved as one
        self.assertEqual(header[:2], ['Move 1 file in %s?' % (self.dst_root,),
                                      '  old/ -> photos/ (a dir, with its 1 file, moved as one)'])
        self.assertEqual(self.pick_option.call_args.kwargs['label'], ('RENAME', 'cyan'))

    def test_rename_in_src_moves_the_file_to_its_matchs_path(self):
        self.browse(['Rename 1 file of these', YES])
        self.assertTrue(os.path.isfile(os.path.join(self.src_root, 'old/x.jpg')))
        self.assertFalse(os.path.exists(os.path.join(self.src_root, 'photos/x.jpg')))
        self.assertEqual(self.src_index.files_named('x.jpg'), {'old/x.jpg': 9})

    def test_the_menu_counts_the_files_with_a_sure_match(self):
        self.browse([NOTHING])
        options = helpers.labels_of(self.pick_option.call_args.args[0])
        self.assertIn("Rename the files matching 1 of these to these paths, in %s" % (self.dst_root,), options)
        self.assertIn("Rename 1 file of these to their matches' paths, in %s" % (self.src_root,), options)

    def test_a_renamed_file_is_compared_then_renamed(self):
        # dst has big.mov as clip.mov, and another file of its size
        big = b'x' * elsewhere.RENAMED_MIN_SIZE
        for root, relpath, contents in ((self.src_root, 'videos/big.mov', big),
                                        (self.dst_root, 'v/clip.mov', big),
                                        (self.dst_root, 'v/other.mov', b'y' * len(big))):
            os.makedirs(os.path.dirname(os.path.join(root, relpath)), exist_ok=True)
            with open(os.path.join(root, relpath), 'wb') as f:
                f.write(contents)
        self.src = localdiskdirtree.LocalDiskDirTree(self.src_root, True)
        self.dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, True)
        sync = Sync(self.src, self.dst)
        picks = [['videos/big.mov'], None]
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)), \
                helpers.answering_option_picker(['Rename the', YES]) as self.pick_option, \
                mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            sync.browse()
        self.assertEqual(sync.checked['videos/big.mov'], {'v/clip.mov': True, 'v/other.mov': False})
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'videos/big.mov')))
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'v/other.mov')))
        self.assertIn('  v/clip.mov -> videos/big.mov', self.pick_option.call_args.kwargs['header'])

    def test_a_rename_with_none_surely_there_after_comparing_says_so(self):
        with open(os.path.join(self.dst_root, 'old/x.jpg'), 'w') as f:
            f.write('another!!')
        self.browse(['Rename the'])
        self.assertEqual(messages.show.call_args.args[0], 'Nothing to rename')
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'old/x.jpg')))

    def test_a_dry_run_moves_nothing(self):
        sync = self.browse(['Rename the', YES], is_dry_run=True)
        self.assertTrue(os.path.isfile(os.path.join(self.dst_root, 'old/x.jpg')))
        self.assertFalse(sync.has_changed)
        self.assertEqual(self.pick_files.call_args.kwargs['picked'], ['photos/y.jpg'])


if __name__ == '__main__':
    unittest.main()
