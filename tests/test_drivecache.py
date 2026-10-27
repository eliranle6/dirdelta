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
        self.assertEqual(next(drivecache.entries('/mein')), ('', 'mein', True, False))

    def test_entries_under_a_folder(self):
        entries = [entry[:3] for entry in drivecache.entries('/mein')][1:]
        self.assertEqual(sorted(entries), sorted([
            ('song.mp3', 'song', False),
            ('album', 'album', True),
            ('album/track.mp3', 'track', False),
            ('dup.mp3', 'dup1', False),
            ('dup.mp3', 'dup2', False),
        ]))

    def test_each_folder_comes_before_whats_in_it(self):
        relpaths = [entry[0] for entry in drivecache.entries('/mein')][1:]
        self.assertLess(relpaths.index('album'), relpaths.index('album/track.mp3'))

    def append(self, line):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(line) + '\n')

    def test_trashed_files_are_left_out(self):
        self.append({drivecache.TRASHED_ID_KEY: 'song'})
        relpaths = [entry[0] for entry in drivecache.entries('/mein')]
        self.assertNotIn('song.mp3', relpaths)
        self.assertIn('album/track.mp3', relpaths)

    def test_added_files_and_folders_are_in(self):
        drivecache.add({'id': 'new', 'name': 'new', 'parents': ['album'],
                        'mimeType': drivecache.FOLDER_MIME_TYPE})
        # Without a mimeType (Drive didn't say), a file
        drivecache.add({'id': 'n1', 'name': '1.mp3', 'parents': ['new']})
        drivecache.trash('track')
        found = {relpath: is_dir for relpath, _, is_dir, _ in drivecache.entries('/mein/album')}
        self.assertEqual(found, {'': True, 'new': True, 'new/1.mp3': False})

    def test_count_leaves_out_the_trashed_lines(self):
        before = drivecache.count_entries()
        drivecache.trash('song')
        self.assertEqual(drivecache.count_entries(), before)


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
            _item('eliran', 'eliran', 'ROOT', FOLDER),
            _item('sheet', 'Budget', 'eliran', 'application/vnd.google-apps.spreadsheet'),
            _item('shortcut', 'Link', 'eliran', 'application/vnd.google-apps.shortcut'),
            _item('jam', 'Board', 'eliran', 'application/vnd.google-apps.jam'),
            _item('song', 'song.mp3', 'eliran'),
        ])
        self.assertEqual(sorted(drivecache.entries('/eliran'))[1:], [
            ('Board.gjam', 'jam', False, True),
            ('Budget.gsheet', 'sheet', False, True),
            ('Link.glink', 'shortcut', False, True),
            ('song.mp3', 'song', False, False),
        ])

    def test_a_google_file_named_like_a_folder_is_fine(self):
        self.assertEqual(self.entries('/eliran', [
            _item('eliran', 'eliran', 'ROOT', FOLDER),
            _item('folder', 'Budget', 'eliran', FOLDER),
            _item('sheet', 'Budget', 'eliran', 'application/vnd.google-apps.spreadsheet'),
        ]), [('Budget', 'folder', True), ('Budget.gsheet', 'sheet', False)])

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
