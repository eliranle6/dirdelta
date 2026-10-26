import json
import os
import tempfile
import unittest
from unittest import mock

from dirdelta import drivecache
from test_clouddirtree import ITEMS


class EntriesTest(unittest.TestCase):
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-drive-cache-')
        with os.fdopen(fd, 'w') as f:
            f.write('not a JSON line, skipped\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        patcher = mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.remove, self.cache)

    def test_the_folder_itself_comes_first(self):
        self.assertEqual(next(drivecache.entries('/mein')), ('', 'mein', True))

    def test_entries_under_a_folder(self):
        entries = list(drivecache.entries('/mein'))[1:]
        self.assertEqual(sorted(entries), sorted([
            ('song.mp3', 'song', False),
            ('album', 'album', True),
            ('album/track.mp3', 'track', False),
            ('dup.mp3', 'dup1', False),
            ('dup.mp3', 'dup2', False),
        ]))

    def test_each_folder_comes_before_whats_in_it(self):
        relpaths = [relpath for relpath, _, _ in drivecache.entries('/mein')][1:]
        self.assertLess(relpaths.index('album'), relpaths.index('album/track.mp3'))


FOLDER = drivecache.FOLDER_MIME_TYPE


def _item(id, name, parent, mime='audio/mpeg'):
    return {'id': id, 'name': name, 'parents': [parent], 'mimeType': mime}


class CacheContentsTest(unittest.TestCase):
    """entries() on a cache written by each test, with My Drive's root's id first"""
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-drive-cache-')
        os.close(fd)
        patcher = mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.remove, self.cache)

    def entries(self, inner_rootpath, items, root_line=True):
        with open(self.cache, 'w') as f:
            if root_line:
                f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            for item in items:
                f.write(json.dumps(item) + '\n')
        # Without the folder itself
        return sorted(drivecache.entries(inner_rootpath))[1:]

    def test_google_docs_and_shortcuts_are_left_out(self):
        self.assertEqual(self.entries('/eliran', [
            _item('eliran', 'eliran', 'ROOT', FOLDER),
            _item('doc', 'Budget', 'eliran', 'application/vnd.google-apps.spreadsheet'),
            _item('shortcut', 'Link', 'eliran', 'application/vnd.google-apps.shortcut'),
            _item('song', 'song.mp3', 'eliran'),
        ]), [('song.mp3', 'song', False)])

    def test_a_missing_folder_is_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'no folder /nope'):
            self.entries('/nope', [_item('eliran', 'eliran', 'ROOT', FOLDER)])

    def test_a_file_is_not_a_folder(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'no folder /song.mp3'):
            self.entries('/song.mp3', [_item('song', 'song.mp3', 'ROOT')])

    def test_an_empty_folder_has_no_entries(self):
        self.assertEqual(self.entries('/eliran', [_item('eliran', 'eliran', 'ROOT', FOLDER)]), [])

    def test_the_whole_drive(self):
        self.assertEqual(self.entries('/', [_item('song', 'song.mp3', 'ROOT')]),
                         [('song.mp3', 'song', False)])

    def test_files_outside_my_drive_are_left_out(self):
        # Shared with the user (no parents), or in a folder the user can't see
        shared = {'id': 'shared', 'name': 'shared.mp3', 'mimeType': 'audio/mpeg'}
        self.assertEqual(self.entries('/', [
            _item('song', 'song.mp3', 'ROOT'), shared, _item('orphan', 'orphan.mp3', 'UNSEEN')]),
            [('song.mp3', 'song', False)])

    def test_an_old_cache_without_the_root_line_still_works(self):
        self.assertEqual(self.entries('/', [_item('song', 'song.mp3', 'ROOT')], root_line=False),
                         [('song.mp3', 'song', False)])

    def test_an_old_cache_with_files_outside_my_drive_must_be_refreshed(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'refresh'):
            self.entries('/', [_item('song', 'song.mp3', 'ROOT'), _item('orphan', 'orphan.mp3', 'UNSEEN')],
                         root_line=False)

    def test_same_named_folders_are_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, r'2 folders or files named /eliran/album'):
            self.entries('/eliran', [
                _item('eliran', 'eliran', 'ROOT', FOLDER),
                _item('album1', 'album', 'eliran', FOLDER),
                _item('album2', 'album', 'eliran', FOLDER),
            ])

    def test_a_folder_and_a_file_of_the_same_name_are_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'named /eliran/album'):
            self.entries('/eliran', [
                _item('eliran', 'eliran', 'ROOT', FOLDER),
                _item('album', 'album', 'eliran', FOLDER),
                _item('albumfile', 'album', 'eliran'),
            ])

    def test_same_named_folders_on_the_way_are_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, '2 folders named /eliran'):
            self.entries('/eliran', [
                _item('eliran1', 'eliran', 'ROOT', FOLDER),
                _item('eliran2', 'eliran', 'ROOT', FOLDER),
            ])

    def test_same_named_things_elsewhere_are_fine(self):
        self.assertEqual(self.entries('/eliran', [
            _item('eliran', 'eliran', 'ROOT', FOLDER),
            _item('other1', 'other', 'ROOT', FOLDER),
            _item('other2', 'other', 'ROOT', FOLDER),
            _item('bad', 'a/b', 'other1'),
        ]), [])

    def test_a_slash_in_a_name_is_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, "a '/' in the name of /eliran/2024/25.pdf"):
            self.entries('/eliran', [
                _item('eliran', 'eliran', 'ROOT', FOLDER),
                _item('report', '2024/25.pdf', 'eliran'),
            ])

    def test_all_the_names_to_fix_are_listed(self):
        with self.assertRaises(drivecache.DriveCacheError) as raised:
            self.entries('/eliran', [
                _item('eliran', 'eliran', 'ROOT', FOLDER),
                _item('sub', 'sub', 'eliran', FOLDER),
                _item('one', '1/2', 'eliran'),
                _item('two', '3/4', 'sub'),
            ])
        self.assertIn('/eliran/1/2', str(raised.exception))
        self.assertIn('/eliran/sub/3/4', str(raised.exception))
