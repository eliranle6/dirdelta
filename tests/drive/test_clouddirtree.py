"""A Drive tree read from the cache: its files, and what's known of them"""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from clouddirtree_support import ITEMS, drive_item


class CloudDirTreeTest(unittest.TestCase):
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-cloud-cache-')
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        patcher = mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(helpers.remove_drive_cache, self.cache)

    def _relpaths(self, tree):
        return sorted(entry.relpath for entry in tree.iter_files())

    def test_builds_files_under_the_requested_folder_only(self):
        tree = clouddirtree.factory('cloud/mein')
        self.assertIn('song.mp3', self._relpaths(tree))
        self.assertIn('album/track.mp3', self._relpaths(tree))
        self.assertNotIn('elsewhere.mp3', self._relpaths(tree))

    def test_same_named_files_both_kept_with_dup_suffix(self):
        tree = clouddirtree.factory('cloud/mein')
        dups = [path for path in self._relpaths(tree) if path.startswith('dup.mp3')]
        self.assertEqual(len(dups), 2)
        self.assertIn('dup.mp3', dups)

    def google_tree(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(drive_item('sheet', 'Budget', 'mein', 'application/vnd.google-apps.spreadsheet')) + '\n')
        return clouddirtree.factory('cloud/mein')

    def test_google_files_are_in_but_cant_be_copied_out(self):
        tree = self.google_tree()
        self.assertIn('Budget.gsheet', self._relpaths(tree))
        self.assertIn('Google file', tree.cant_fetch('Budget.gsheet'))
        self.assertIsNone(tree.cant_fetch('song.mp3'))
        with self.assertRaises(OSError):
            tree.fetch_file('Budget.gsheet', '/nowhere')

    def test_the_confirmation_of_copying_google_files_says_theyre_skipped(self):
        notes = self.google_tree().copy_notes(['song.mp3', 'Budget.gsheet'])
        self.assertIn("can't be copied", notes[0])
        self.assertEqual(notes[1:], ['  Budget.gsheet'])
        self.assertEqual(self.google_tree().copy_notes(['song.mp3']), [])

    def test_the_confirmation_of_a_removal_says_what_is_trashed_whole_and_the_google_files(self):
        notes = self.google_tree().removal_notes(['album/track.mp3', 'Budget.gsheet'])
        self.assertTrue(notes[0].startswith('Trashing 1 folders whole'))
        self.assertEqual(notes[1], '  album/')
        self.assertTrue(notes[2].startswith('Including 1 Google files'))
        self.assertEqual(notes[3], '  Budget.gsheet')

    def test_file_sizes_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(drive_item('sized', 'sized.mp3', 'mein'), size='1234')) + '\n')
        tree = self.google_tree()
        self.assertEqual(tree.file_size('sized.mp3'), 1234)
        self.assertIsNone(tree.file_size('song.mp3'))
        self.assertIsNone(tree.file_size('Budget.gsheet'))

    def test_modification_times_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(drive_item('t', 't.mp3', 'mein'), modifiedTime='2024-07-01T14:03:22.000Z')) + '\n')
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.modified_time('t.mp3'), 1719842602)
        self.assertIsNone(tree.modified_time('song.mp3'))

    def test_dates_taken_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(drive_item('photo', 'x.jpg', 'mein', 'image/jpeg'),
                                    imageMediaMetadata={'time': '2024:07:01 14:03:22'})) + '\n')
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.date_taken('x.jpg'), '2024-07-01 14:03:22')
        self.assertIsNone(tree.date_taken('song.mp3'))

    def test_hashes_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(drive_item('h', 'h.mp3', 'mein'), sha1Checksum='S1', sha256Checksum='S256')) + '\n')
            f.write(json.dumps(dict(drive_item('old', 'old.mp3', 'mein'), sha256Checksum='O256')) + '\n')
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.known_hashes('h.mp3'), ('sha1', 'sha256'))
        self.assertEqual(tree.content_hash('h.mp3', 'sha1'), 'S1')
        # A line from before SHA-1 was asked for
        self.assertEqual(tree.known_hashes('old.mp3'), ('sha256',))
        self.assertIsNone(tree.content_hash('old.mp3', 'sha1'))
        self.assertEqual(tree.known_hashes('song.mp3'), ())
        self.assertIsNone(tree.local_path('song.mp3'))

    def test_files_by_name_has_same_named_files_by_their_name(self):
        found = clouddirtree.factory('cloud/mein').files_by_name()
        self.assertEqual(len(found['dup.mp3']), 2)
        self.assertEqual(found['track.mp3'], [('album/track.mp3', None)])

    def test_fullpath_is_the_path_inside_the_drive(self):
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.get_node('album/track.mp3').data.fullpath, '/mein/album/track.mp3')


if __name__ == '__main__':
    unittest.main()
