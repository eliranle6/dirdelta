"""Removing a Drive tree's files to Drive's trash, a whole folder as one"""
import unittest
from unittest import mock

from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from clouddirtree_support import CloudDirTreeChangesTest, _http_error


class RemovalsTest(CloudDirTreeChangesTest):
    """Removals"""

    def test_remove_moves_to_the_trash(self):
        self.remove(['song.mp3'])
        self.service.files.return_value.update.assert_called_once_with(fileId='song',
                                                                       body={'trashed': True})
        self.assertNotIn('song.mp3', self.tree)
        self.assertIn("Remove complete: removed 1 of 1 files from cloud/mein (to Drive's trash)",
                      self.lines())

    def test_a_folder_all_of_whose_files_are_removed_is_trashed_as_one(self):
        self.remove(['album/track.mp3'])
        self.assertEqual(self.trashed(), ['album'])
        self.assertNotIn('album', self.tree)
        self.assertIn('Removing folder album/ and its 1 files (1 out of 1)', self.lines())
        self.assertIn("Remove complete: removed 1 of 1 files from cloud/mein (to Drive's trash)",
                      self.lines())
        # The cache has it trashed, and what's in it
        self.assertIsNone(clouddirtree.factory('cloud/mein').get_node('album'))
        self.assertFalse(drivecache.stale_paths())

    def test_only_the_topmost_whole_folders_are_trashed(self):
        for relpath, cloud_id in (('a/1.mp3', 'one'), ('a/b/2.mp3', 'two'), ('a/b/c/3.mp3', 'three'),
                                  ('d/4.mp3', 'four'), ('d/e/5.mp3', 'five')):
            self.add(relpath, cloud_id)
        self.remove(['a/1.mp3', 'a/b/2.mp3', 'a/b/c/3.mp3', 'd/e/5.mp3'])
        # d keeps 4.mp3, so only d/e goes whole
        self.assertCountEqual(self.trashed(), ['a', 'e'])
        self.assertIn('d/4.mp3', self.tree)

    def test_a_folder_with_a_file_not_picked_is_kept(self):
        # The picker didn't show it: the other replica has it too
        self.add('album/also-elsewhere.mp3', 'elsewhere')
        self.remove(['album/track.mp3'])
        self.assertEqual(self.trashed(), ['track'])
        self.assertIn('album/also-elsewhere.mp3', self.tree)
        self.service.files.return_value.list.assert_not_called()

    def test_files_at_the_root_are_trashed_one_by_one_not_the_root(self):
        self.remove(['song.mp3', 'album/track.mp3', 'dup.mp3', 'dup.mp3___DUP__dup2'])
        self.assertCountEqual(self.trashed(), ['song', 'album', 'dup1', 'dup2'])

    def test_a_folder_that_drive_has_more_in_is_kept(self):
        # Since the cache was made, a file was added to a/b in Drive
        for relpath, cloud_id in (('a/1.mp3', 'one'), ('a/b/2.mp3', 'two'), ('a/c/3.mp3', 'three')):
            self.add(relpath, cloud_id)
        self.listed = lambda query: ([{'id': 'new', 'parents': ['b']}]
                                     if "'b' in parents" in query else [])
        self.remove(['a/1.mp3', 'a/b/2.mp3', 'a/c/3.mp3'])
        # a and b are kept; c goes whole, and the others one by one
        self.assertCountEqual(self.trashed(), ['c', 'one', 'two'])
        self.assertIn('a/b', self.tree)
        self.assertTrue(any(line.startswith('Drive has files in 1 folders') for line in self.lines()))

    def test_if_drive_cant_be_asked_the_files_are_trashed_one_by_one(self):
        def listed(query):
            raise _http_error()
        self.listed = listed
        self.remove(['album/track.mp3'])
        self.assertEqual(self.trashed(), ['track'])

    def test_a_dry_run_says_which_folders_it_would_trash(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.remove(['album/track.mp3', 'song.mp3'])
        self.service.files.return_value.update.assert_not_called()
        self.service.files.return_value.list.assert_not_called()
        self.assertIn('Dry run, not removing folder album/ and its 1 files (1 out of 2)', self.lines())
        self.assertIn('album', self.tree)

    def test_a_failed_remove_keeps_the_file(self):
        self.service.files.return_value.update.return_value.execute.side_effect = _http_error()
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.assertIn('song.mp3', self.tree)

    def test_a_kept_folder_isnt_trashed_by_a_move_or_a_removal(self):
        self.tree.keep_dirs(['album'])
        self.move('album/track.mp3', 'track.mp3')
        self.assertEqual(self.trashed(), [])
        self.assertIn('album', self.tree)

    def test_a_kept_folder_isnt_trashed_whole_its_files_are(self):
        self.tree.keep_dirs(['album'])
        self.tree.remove_files([self.tree.get_node('album/track.mp3').data])
        self.assertEqual(self.trashed(), ['track'])
        self.assertIn('album', self.tree)


if __name__ == '__main__':
    unittest.main()
