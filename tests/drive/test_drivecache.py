"""The Drive cache: its entries, changes, import of the old file, and stale folders"""
import json
import os
import sqlite3
import tempfile
import unittest
from clouddirtree_support import ITEMS
from unittest import mock

import helpers
from dirdelta.drive import drivecache


class EntriesTest(unittest.TestCase):
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-drive-cache-')
        with os.fdopen(fd, 'w') as f:
            f.write('not a JSON line, skipped\n')
            f.write(json.dumps({drivecache.ROOT_ID_KEY: 'ROOT'}) + '\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        patcher = mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', self.cache)
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
        with mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', self.cache + '-missing.txt'):
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
        with mock.patch('dirdelta.drive.drivecache.database.put_row', side_effect=KeyboardInterrupt):
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


class StaleTest(unittest.TestCase):
    def setUp(self):
        self.cache = os.path.join(tempfile.mkdtemp(prefix='dirstuff-drive-cache-'), 'files.txt')
        patcher = mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', self.cache)
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


if __name__ == '__main__':
    unittest.main()
