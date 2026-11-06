import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from dirdelta import drivecache
import helpers
from test_clouddirtree import ITEMS


class EntriesTest(unittest.TestCase):
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-drive-cache-')
        with os.fdopen(fd, 'w') as f:
            f.write('not a JSON line, skipped\n')
            f.write(json.dumps({drivecache.ROOT_ID_KEY: 'ROOT'}) + '\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        patcher = mock.patch('dirdelta.drivecache.LINES_FILE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(helpers.remove_drive_cache, self.cache)

    def test_the_folder_itself_comes_first(self):
        self.assertEqual(next(drivecache.entries('/mein')), ('', 'mein', True, False, None, None, {}, None))

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
        found = {entry.relpath: entry.is_dir for entry in drivecache.entries('/mein/album')}
        self.assertEqual(found, {'': True, 'new': True, 'new/1.mp3': False})

    def test_whats_under_a_folder_can_be_replaced(self):
        # In Drive now: song.mp3 renamed, album and the dups gone, a new folder with a file
        drivecache.replace_under('mein', [
            {'id': 'song', 'name': 'renamed.mp3', 'parents': ['mein']},
            {'id': 'new', 'name': 'new', 'parents': ['mein'], 'mimeType': drivecache.FOLDER_MIME_TYPE},
            {'id': 'n1', 'name': '1.mp3', 'parents': ['new']},
        ], 'ROOT')
        found = {entry.relpath: entry.cloud_id for entry in drivecache.entries('/mein')}
        self.assertEqual(found, {'': 'mein', 'renamed.mp3': 'song', 'new': 'new', 'new/1.mp3': 'n1'})
        # The rest is as it was
        self.assertEqual([entry[0] for entry in drivecache.entries('/other')], ['', 'elsewhere.mp3'])

    def test_a_file_trashed_and_restored_since_is_back_after_a_replace(self):
        drivecache.trash('song')
        drivecache.replace_under('mein', [{'id': 'song', 'name': 'song.mp3', 'parents': ['mein']}], 'ROOT')
        self.assertEqual([entry[0] for entry in drivecache.entries('/mein')], ['', 'song.mp3'])

    def test_count_under_a_folder(self):
        self.assertEqual(drivecache.count_under('/mein'), 5)
        drivecache.trash('album')
        self.assertEqual(drivecache.count_under('/mein'), 3)
        self.assertIsNone(drivecache.count_under('/nowhere'))
        with mock.patch('dirdelta.drivecache.LINES_FILE', self.cache + '-missing.txt'):
            self.assertIsNone(drivecache.count_under('/mein'))

    def test_with_no_cache_a_replace_makes_one_with_the_root(self):
        helpers.remove_drive_cache(self.cache)
        drivecache.replace_under('mein', [{'id': 'mein', 'name': 'mein', 'parents': ['ROOT'],
                                           'mimeType': drivecache.FOLDER_MIME_TYPE},
                                          {'id': 'song', 'name': 'song.mp3', 'parents': ['mein']}],
                                 'ROOT')
        self.assertEqual(drivecache.root_id(), 'ROOT')
        self.assertEqual([entry[0] for entry in drivecache.entries('/mein')], ['', 'song.mp3'])

    def test_a_replace_cut_off_leaves_it_as_it_was(self):
        before = drivecache.rows()

        def items():
            yield {'id': 'new', 'name': 'new.mp3', 'parents': ['mein']}
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            drivecache.replace_under('mein', items(), 'ROOT')
        self.assertEqual(drivecache.rows(), before)

    def test_the_old_file_is_imported_once_and_kept_aside(self):
        # setUp's, once something's read
        self.assertEqual(drivecache.root_id(), 'ROOT')
        self.assertFalse(os.path.exists(self.cache))
        self.assertTrue(os.path.exists(self.cache + '.bak'))
        self.assertTrue(os.path.exists(os.path.splitext(self.cache)[0] + '.sqlite'))
        self.assertEqual(sorted(md['id'] for md in drivecache.rows()),
                         sorted(item['id'] for item in ITEMS))

    def test_an_import_cut_off_is_done_again(self):
        with mock.patch('dirdelta.drivecache._put', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                drivecache.root_id()
        self.assertTrue(os.path.exists(self.cache))
        self.assertEqual(len(drivecache.rows()), len(ITEMS))

    def test_a_trashed_line_of_the_old_file_is_imported(self):
        self.append({drivecache.TRASHED_ID_KEY: 'song'})
        self.assertNotIn('song', [md['id'] for md in drivecache.rows()])

    def test_a_cache_that_isnt_a_database_says_so(self):
        drivecache.root_id()
        helpers.remove_drive_cache(self.cache)
        with open(os.path.splitext(self.cache)[0] + '.sqlite', 'wb') as f:
            f.write(b'not a database, not at all' * 100)
        with self.assertRaisesRegex(drivecache.DriveCacheError, "can't be read"):
            list(drivecache.entries('/mein'))

    def test_what_another_process_changes_is_read_again(self):
        self.assertEqual(drivecache.count_under('/mein'), 5)
        other = sqlite3.connect(os.path.splitext(self.cache)[0] + '.sqlite')
        with other:
            other.execute('INSERT INTO files (id, parent, md) VALUES (?, ?, ?)',
                          ('y', 'mein', json.dumps({'id': 'y', 'name': 'y.mp3', 'parents': ['mein']})))
        other.close()
        self.assertEqual(drivecache.count_under('/mein'), 6)

    def test_a_cache_replaced_is_opened_anew(self):
        self.assertEqual(drivecache.root_id(), 'ROOT')
        helpers.remove_drive_cache(self.cache)
        self.assertIsNone(drivecache.root_id())

class ParseTest(unittest.TestCase):
    def setUp(self):
        self.cache = os.path.join(tempfile.mkdtemp(prefix='dirstuff-drive-cache-'), 'files.txt')
        with open(self.cache, 'w') as f:
            f.write(json.dumps({drivecache.ROOT_ID_KEY: 'ROOT'}) + '\n')
            f.write(json.dumps({'id': 'a', 'name': 'a', 'parents': ['ROOT'], 'mimeType': drivecache.FOLDER_MIME_TYPE}) + '\n')
        patcher = mock.patch('dirdelta.drivecache.LINES_FILE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

class StaleTest(unittest.TestCase):
    def setUp(self):
        self.cache = os.path.join(tempfile.mkdtemp(prefix='dirstuff-drive-cache-'), 'files.txt')
        patcher = mock.patch('dirdelta.drivecache.LINES_FILE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(drivecache.mark_fresh)

    def test_marked_folders_are_stale_until_unmarked(self):
        self.assertTrue(drivecache.mark_stale('/a'))
        self.assertTrue(drivecache.mark_stale('/b'))
        # Already marked: so it's for whoever marked it first to unmark
        self.assertFalse(drivecache.mark_stale('/a'))
        self.assertEqual(drivecache.stale_paths(), ['/a', '/b'])
        drivecache.unmark_stale('/a')
        self.assertEqual(drivecache.stale_paths(), ['/b'])
        drivecache.unmark_stale('/b')
        self.assertFalse(drivecache.stale_paths())
        self.assertFalse(os.path.exists(os.path.splitext(self.cache)[0] + '.stale'))

    def test_a_refresh_makes_what_it_read_fresh(self):
        for path in ('/a', '/a/b', '/ab', '/c'):
            drivecache.mark_stale(path)
        drivecache.mark_fresh('/a')
        self.assertEqual(drivecache.stale_paths(), ['/ab', '/c'])
        drivecache.mark_fresh()
        self.assertFalse(drivecache.stale_paths())

    def test_changing_is_stale_only_while_its_made_or_when_its_cut_off(self):
        with drivecache.changing('/a'):
            self.assertEqual(drivecache.stale_paths(), ['/a'])
        self.assertFalse(drivecache.stale_paths())
        # A failure changed nothing in Drive
        with self.assertRaises(ValueError), drivecache.changing('/a'):
            raise ValueError
        self.assertFalse(drivecache.stale_paths())
        # Ctrl-C may have changed it, unless what was done was settled first
        with self.assertRaises(KeyboardInterrupt), drivecache.changing('/a') as changes:
            changes.settled = True
            raise KeyboardInterrupt
        self.assertFalse(drivecache.stale_paths())
        with self.assertRaises(KeyboardInterrupt), drivecache.changing('/a'):
            raise KeyboardInterrupt
        self.assertEqual(drivecache.stale_paths(), ['/a'])
        # Marked before: left for whoever marked it
        with drivecache.changing('/a'):
            pass
        self.assertEqual(drivecache.stale_paths(), ['/a'])



FOLDER = drivecache.FOLDER_MIME_TYPE


def _item(id, name, parent, mime='audio/mpeg'):
    return {'id': id, 'name': name, 'parents': [parent], 'mimeType': mime}


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
        patcher = mock.patch('dirdelta.drivecache.LINES_FILE', self.cache)
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
            _item('eliran', 'eliran', 'ROOT', FOLDER),
            _item('sheet', 'Budget', 'eliran', 'application/vnd.google-apps.spreadsheet'),
            _item('shortcut', 'Link', 'eliran', 'application/vnd.google-apps.shortcut'),
            _item('jam', 'Board', 'eliran', 'application/vnd.google-apps.jam'),
            _item('song', 'song.mp3', 'eliran'),
        ])
        self.assertEqual(sorted(entry[:4] for entry in drivecache.entries('/eliran'))[1:], [
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

    def test_the_whole_drive(self):
        self.assertEqual(self.entries('/', [_item('song', 'song.mp3', 'ROOT')]),
                         [('song.mp3', 'song', False)])

    def test_files_outside_my_drive_are_left_out(self):
        # Shared with the user (no parents), or in a folder the user can't see
        shared = {'id': 'shared', 'name': 'shared.mp3', 'mimeType': 'audio/mpeg'}
        self.assertEqual(self.entries('/', [
            _item('song', 'song.mp3', 'ROOT'), shared, _item('orphan', 'orphan.mp3', 'UNSEEN')]),
            [('song.mp3', 'song', False)])

    def test_a_cache_without_the_root_line_must_be_refreshed(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, 'refresh'):
            self.entries('/', [_item('song', 'song.mp3', 'ROOT')], root_line=False)

    def test_refreshing_a_cache_without_the_root_line_makes_it_readable(self):
        self.write([_item('old', 'old.mp3', 'ROOT')], root_line=False)
        drivecache.replace_under('ROOT', [_item('song', 'song.mp3', 'ROOT')], 'ROOT')
        self.assertEqual(drivecache.root_id(), 'ROOT')
        self.assertEqual([entry.relpath for entry in drivecache.entries('/')][1:], ['song.mp3'])

    def test_same_named_folders_are_an_error(self):
        with self.assertRaisesRegex(drivecache.DriveCacheError, r'2 folders or files named /eliran/album'):
            self.entries('/eliran', [
                _item('eliran', 'eliran', 'ROOT', FOLDER),
                _item('album1', 'album', 'eliran', FOLDER),
                _item('album2', 'album', 'eliran', FOLDER),
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
