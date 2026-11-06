"""What the cache's entries are made of: Google files, names that can't be paths, times"""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.drive import drivecache
from clouddirtree_support import FOLDER, drive_item


class ModifiedTimeTest(unittest.TestCase):
    def test_drives_modified_time(self):
        self.assertEqual(drivecache.modified_time({'modifiedTime': '2024-07-01T14:03:22.123Z'}), 1719842602)
        self.assertIsNone(drivecache.modified_time({}))
        self.assertIsNone(drivecache.modified_time({'modifiedTime': 'yesterday'}))
        self.assertEqual(drivecache.rfc3339(1719842602), '2024-07-01T14:03:22.000000Z')


class CacheContentsTest(unittest.TestCase):
    """entries() on a cache written by each test, with My Drive's root's id first"""
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-drive-cache-')
        os.close(fd)
        patcher = mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(helpers.remove_drive_cache, self.cache)

    def write(self, items, root_line=True):
        with open(self.cache, 'w') as f:
            if root_line:
                f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            for item in items:
                f.write(json.dumps(item) + '\n')

    def entries(self, inner_rootpath, items, root_line=True):
        self.write(items, root_line)
        # Without the folder itself, and without whether each is a Google file
        return sorted(entry[:3] for entry in drivecache.entries(inner_rootpath))[1:]

    def test_google_files_are_in_with_their_extensions(self):
        self.write([
            drive_item('eliran', 'eliran', 'ROOT', FOLDER),
            drive_item('sheet', 'Budget', 'eliran', 'application/vnd.google-apps.spreadsheet'),
            drive_item('shortcut', 'Link', 'eliran', 'application/vnd.google-apps.shortcut'),
            drive_item('jam', 'Board', 'eliran', 'application/vnd.google-apps.jam'),
            drive_item('song', 'song.mp3', 'eliran'),
        ])
        self.assertEqual(sorted(entry[:4] for entry in drivecache.entries('/eliran'))[1:], [
            ('Board.gjam', 'jam', False, True),
            ('Budget.gsheet', 'sheet', False, True),
            ('Link.glink', 'shortcut', False, True),
            ('song.mp3', 'song', False, False),
        ])

    def test_a_google_file_named_like_a_folder_is_fine(self):
        self.assertEqual(self.entries('/eliran', [
            drive_item('eliran', 'eliran', 'ROOT', FOLDER),
            drive_item('folder', 'Budget', 'eliran', FOLDER),
            drive_item('sheet', 'Budget', 'eliran', 'application/vnd.google-apps.spreadsheet'),
        ]), [('Budget', 'folder', True), ('Budget.gsheet', 'sheet', False)])

    def test_a_missing_folder_is_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'no folder /nope'):
            self.entries('/nope', [drive_item('eliran', 'eliran', 'ROOT', FOLDER)])

    def test_a_file_is_not_a_folder(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'no folder /song.mp3'):
            self.entries('/song.mp3', [drive_item('song', 'song.mp3', 'ROOT')])

    def test_the_whole_drive(self):
        self.assertEqual(self.entries('/', [drive_item('song', 'song.mp3', 'ROOT')]),
                         [('song.mp3', 'song', False)])

    def test_files_outside_my_drive_are_left_out(self):
        # Shared with the user (no parents), or in a folder the user can't see
        shared = {'id': 'shared', 'name': 'shared.mp3', 'mimeType': 'audio/mpeg'}
        self.assertEqual(self.entries('/', [
            drive_item('song', 'song.mp3', 'ROOT'), shared, drive_item('orphan', 'orphan.mp3', 'UNSEEN')]),
            [('song.mp3', 'song', False)])

    def test_a_cache_without_the_root_line_must_be_refreshed(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'refresh'):
            self.entries('/', [drive_item('song', 'song.mp3', 'ROOT')], root_line=False)

    def test_refreshing_a_cache_without_the_root_line_makes_it_readable(self):
        self.write([drive_item('old', 'old.mp3', 'ROOT')], root_line=False)
        drivecache.replace_under('ROOT', [drive_item('song', 'song.mp3', 'ROOT')], 'ROOT')
        self.assertEqual(drivecache.root_id(), 'ROOT')
        self.assertEqual([entry.relpath for entry in drivecache.entries('/')][1:], ['song.mp3'])

    def test_same_named_folders_are_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, r'2 folders or files named /eliran/album'):
            self.entries('/eliran', [
                drive_item('eliran', 'eliran', 'ROOT', FOLDER),
                drive_item('album1', 'album', 'eliran', FOLDER),
                drive_item('album2', 'album', 'eliran', FOLDER),
            ])

    def test_same_named_folders_on_the_way_are_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, '2 folders named /eliran'):
            self.entries('/eliran', [
                drive_item('eliran1', 'eliran', 'ROOT', FOLDER),
                drive_item('eliran2', 'eliran', 'ROOT', FOLDER),
            ])

    def test_same_named_things_elsewhere_are_fine(self):
        self.assertEqual(self.entries('/eliran', [
            drive_item('eliran', 'eliran', 'ROOT', FOLDER),
            drive_item('other1', 'other', 'ROOT', FOLDER),
            drive_item('other2', 'other', 'ROOT', FOLDER),
            drive_item('bad', 'a/b', 'other1'),
        ]), [])

    def test_a_slash_in_a_name_is_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, "a '/' in the name of /eliran/2024/25.pdf"):
            self.entries('/eliran', [
                drive_item('eliran', 'eliran', 'ROOT', FOLDER),
                drive_item('report', '2024/25.pdf', 'eliran'),
            ])

    def test_all_the_names_to_fix_are_listed(self):
        with self.assertRaises(drivecache.DriveCacheError) as raised:
            self.entries('/eliran', [
                drive_item('eliran', 'eliran', 'ROOT', FOLDER),
                drive_item('sub', 'sub', 'eliran', FOLDER),
                drive_item('one', '1/2', 'eliran'),
                drive_item('two', '3/4', 'sub'),
            ])
        self.assertIn('/eliran/1/2', str(raised.exception))
        self.assertIn('/eliran/sub/3/4', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
