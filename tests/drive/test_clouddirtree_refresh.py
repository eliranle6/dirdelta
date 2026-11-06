"""Reading a Drive folder anew into the cache"""
import unittest
from googleapiclient.errors import HttpError
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from clouddirtree_support import CloudDirTreeChangesTest, FOLDER, _http_error, _item


class RefreshTest(CloudDirTreeChangesTest):
    """Refreshes"""

    def test_refresh_reads_the_folder_anew_from_drive(self):
        self.drive_has(self.DRIVE_NOW)
        self.assertEqual(self.tree.refresh_from_drive(), '')
        self.assertEqual(self.relpaths(self.tree), ['new/1.mp3', 'song.mp3'])
        self.assertNotIn('album', self.tree)
        self.assertEqual(self.tree._cloud_ids['new/1.mp3'], 'n1')
        # The cache has it, and has the rest as it was
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud/mein')), ['new/1.mp3', 'song.mp3'])
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud/other')), ['elsewhere.mp3'])
        # The folder found by its name, then asked for what the cache keeps of each, and only
        # what's under the folder
        self.assertTrue(self.queries()[0].startswith("name = 'mein' and 'ROOT' in parents"))
        files = self.service.files.return_value
        self.assertIn(drivecache.FILE_FIELDS, files.list.call_args.kwargs['fields'])
        self.assertTrue(all("'other' in parents" not in query for query in self.queries()))

    def test_refresh_of_a_dir_in_the_tree(self):
        self.drive_has(self.DRIVE_NOW + [_item('album', 'album', 'mein', FOLDER),
                                         _item('t2', 'track2.mp3', 'album')])
        self.assertEqual(self.tree.refresh_from_drive('album'), 'album')
        # Only album was read again
        self.assertEqual(self.relpaths(self.tree), ['album/track2.mp3', 'dup.mp3', 'dup.mp3___DUP__dup2',
                                                   'song.mp3'])
        self.assertTrue(self.queries()[1].startswith("name = 'album' and 'mein' in parents"))

    def test_refresh_of_a_file_or_a_dir_not_in_the_tree_is_of_the_folder_above_it(self):
        self.drive_has(self.DRIVE_NOW + [_item('album', 'album', 'mein', FOLDER)])
        self.assertEqual(self.tree.refresh_from_drive('album/track.mp3'), 'album')
        self.assertEqual(self.tree.refresh_from_drive('album/only/in/the/other'), 'album')
        self.assertEqual(self.tree.refresh_from_drive('nowhere/x.mp3'), '')

    def test_refresh_asks_a_level_of_folders_at_a_time(self):
        self.drive_has([_item('mein', 'mein', 'ROOT', FOLDER)] +
                       [_item('f%d' % (i,), 'f%d' % (i,), 'mein', FOLDER) for i in range(5)] +
                       [_item('x%d' % (i,), 'x.mp3', 'f%d' % (i,)) for i in range(5)])
        with mock.patch('dirdelta.drive.clouddirtree.refresh.MAX_FOLDERS_PER_QUERY', 2):
            self.tree.refresh_from_drive()
        # mein by name, what's in it, then f0-f4 two at a time
        self.assertEqual(len(self.queries()), 1 + 1 + 3)
        self.assertEqual(len(self.relpaths(self.tree)), 5)

    def test_a_failed_refresh_leaves_the_tree_and_the_cache_as_they_were(self):
        cache_before = drivecache.rows()
        def listed(query):
            raise _http_error()
        self.listed = listed
        with self.assertRaises(HttpError):
            self.tree.refresh_from_drive()
        self.assertIn('album/track.mp3', self.tree)
        self.assertEqual(drivecache.rows(), cache_before)

    def test_a_refresh_whose_names_cant_be_paths_leaves_the_tree_as_it_was(self):
        self.drive_has([_item('mein', 'mein', 'ROOT', FOLDER), _item('a1', 'a', 'mein', FOLDER),
                        _item('a2', 'a', 'mein', FOLDER)])
        with self.assertRaises(drivecache.DriveCacheError):
            self.tree.refresh_from_drive()
        self.assertIn('album/track.mp3', self.tree)

    def test_a_folder_drive_no_longer_has_is_an_error(self):
        self.drive_has([_item('other', 'other', 'ROOT', FOLDER)])
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'no folder /mein'):
            self.tree.refresh_from_drive()

    def test_quotes_in_a_name_are_escaped(self):
        self.drive_has([_item('q', "it's", 'ROOT', FOLDER), _item('in', 'in.mp3', 'q')])
        clouddirtree.refresh_cache("/it's")
        self.assertTrue(self.queries()[0].startswith("name = 'it\\'s'"))
        self.assertEqual(self.relpaths(clouddirtree.factory("cloud/it's")), ['in.mp3'])

    def test_a_refresh_marks_only_the_folder_fresh(self):
        self.drive_has(self.DRIVE_NOW)
        for path in ('/mein', '/mein/album', '/other'):
            drivecache.mark_stale(path)
        self.tree.refresh_from_drive()
        self.assertEqual(drivecache.stale_paths(), ['/other'])

    def test_a_failed_refresh_leaves_the_folder_stale(self):
        drivecache.mark_stale('/mein')
        self.drive_has([])
        with self.assertRaises(drivecache.DriveCacheError):
            self.tree.refresh_from_drive()
        self.assertEqual(drivecache.stale_paths(), ['/mein'])

    def test_with_no_cache_a_refresh_makes_one(self):
        helpers.remove_drive_cache(self.cache)
        self.drive_has(self.DRIVE_NOW)
        clouddirtree.refresh_cache('/mein')
        self.assertEqual(drivecache.root_id(), 'ROOT')
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud/mein')), ['new/1.mp3', 'song.mp3'])

    def test_refresh_of_all_of_drive(self):
        self.drive_has(self.DRIVE_NOW)
        clouddirtree.refresh_cache('/')
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud')),
                         ['mein/new/1.mp3', 'mein/song.mp3', 'other/elsewhere.mp3', 'other/new2.mp3'])

    def test_refresh_expects_as_many_as_the_cache_has_there(self):
        self.drive_has(self.DRIVE_NOW)
        with mock.patch('dirdelta.ui.messages.print_progress') as print_progress:
            self.tree.refresh_from_drive()
        # The cache has 5 in mein: song.mp3, album, its track.mp3 and the two dup.mp3
        self.assertEqual(print_progress.call_args_list[0].args[0],
                         'Read 0 of about 5 files and folders (0%)')


if __name__ == '__main__':
    unittest.main()
