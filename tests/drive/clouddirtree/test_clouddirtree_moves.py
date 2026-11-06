"""Moving and copying files within Drive"""
import json
import unittest
from unittest import mock

from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from clouddirtree_support import CloudDirTreeChangesTest, http_error, drive_item


class MovesTest(CloudDirTreeChangesTest):
    """Moves and copies within Drive"""

    def test_move_renames_and_reparents_the_file_in_drive(self):
        self.assertEqual(self.move('song.mp3', 'album/moved.mp3'), [('song.mp3', 'album/moved.mp3')])
        update = self.service.files.return_value.update
        update.assert_called_once_with(fileId='song', body={'name': 'moved.mp3'}, addParents='album',
                                       removeParents='mein', fields=drivecache.FILE_FIELDS)
        self.assertNotIn('song.mp3', self.tree)
        self.assertEqual(self.tree._cloud_ids['album/moved.mp3'], 'song')
        # The cache has it at its new path, by the same id
        found = {entry.relpath: entry.cloud_id for entry in drivecache.entries('/mein')}
        self.assertEqual(found['album/moved.mp3'], 'song')
        self.assertNotIn('song.mp3', found)
        self.assertFalse(drivecache.stale_paths())
        self.assertIn('Move complete: moved 1 of 1 files in cloud/mein', self.lines())

    def test_listed_says_sizes_and_drives_hashes(self):
        self.tree._infos['song.mp3'] = clouddirtree.FileInfo(5, None, {'sha1': 'S'}, None, False)
        listed = self.tree.listed('sha1')
        self.assertEqual(listed['song.mp3'], (5, 'S'))
        self.assertEqual(sorted(listed), sorted(file_entry.relpath for file_entry in self.tree.iter_files()))

    def test_a_move_to_another_tree_is_a_rename_in_drive_and_goes_with_whats_known(self):
        other = clouddirtree.factory('cloud/other')
        self.tree._infos['song.mp3'] = clouddirtree.FileInfo(5, None, {'sha1': 'S'}, None, False)
        self.service.files.return_value.update.return_value.execute.return_value = {
            'id': 'song', 'name': 'moved.mp3', 'mimeType': 'audio/mpeg', 'size': '5'}
        self.assertEqual(self.tree.move_files([('song.mp3', 'new/moved.mp3')], other), [('song.mp3', 'new/moved.mp3')])
        update = self.service.files.return_value.update.call_args.kwargs
        self.assertEqual(update['fileId'], 'song')
        self.assertEqual(update['body'], {'name': 'moved.mp3'})
        self.assertEqual(update['removeParents'], 'mein')
        # In other's new folder, made there
        self.assertEqual(update['addParents'], other._cloud_ids['new'])
        self.assertNotIn('song.mp3', self.tree)
        self.assertIn('new/moved.mp3', other)
        self.assertEqual(other.known_hash('new/moved.mp3', 'sha1'), 'S')
        self.assertEqual(other._cloud_ids['new/moved.mp3'], 'song')
        self.assertFalse(self.tree.has_file('song.mp3'))
        self.assertEqual(self.tree.known_hash('song.mp3', 'sha1'), None)
        self.assertFalse(drivecache.stale_paths())
        # The cache agrees
        self.assertIn('new/moved.mp3', [entry.relpath for entry in drivecache.entries('/other')])
        self.assertNotIn('song.mp3', [entry.relpath for entry in drivecache.entries('/mein')])

    def test_a_whole_folder_moved_to_another_tree_is_one_request(self):
        other = clouddirtree.factory('cloud/other')
        moves = [('album/track.mp3', 'album/track.mp3')]
        self.service.files.return_value.update.return_value.execute.return_value = {'id': 'album', 'name': 'album'}
        self.assertEqual(self.tree.move_files(moves, other), moves)
        self.assertEqual(self.service.files.return_value.update.call_count, 1)
        self.assertEqual(self.service.files.return_value.update.call_args.kwargs['fileId'], 'album')
        self.assertNotIn('album', self.tree)
        self.assertEqual(other._cloud_ids['album/track.mp3'], 'track')

    def test_a_copy_to_another_tree(self):
        other = clouddirtree.factory('cloud/other')
        self.service.files.return_value.copy.return_value.execute.return_value = {'id': 'copied', 'mimeType': 'audio/mpeg'}
        self.assertEqual(self.tree.copy_files_within([('song.mp3', 'copy.mp3')], other), [('song.mp3', 'copy.mp3')])
        self.assertIn('song.mp3', self.tree)
        self.assertIn('copy.mp3', other)
        self.assertEqual(self.service.files.return_value.copy.call_args.kwargs['body']['parents'], ['other'])

    def test_a_folder_a_move_leaves_empty_is_trashed(self):
        # album/ has only track.mp3
        self.move('album/track.mp3', 'track.mp3')
        self.assertEqual(self.trashed(), ['album'])
        self.assertNotIn('album', self.tree)
        self.assertIn("Moved 1 folders left empty to Drive's trash: album/", self.lines())

    def test_a_folder_drive_has_more_in_isnt_trashed(self):
        self.listed = lambda query: [{'id': 'unknown', 'parents': ['album']}] if 'album' in query else []
        self.move('album/track.mp3', 'track.mp3')
        self.assertEqual(self.trashed(), [])
        self.assertIn('album', self.tree)

    def test_a_folder_with_more_in_it_isnt_trashed(self):
        self.move('song.mp3', 'album/song.mp3')
        self.assertEqual(self.trashed(), [])

    def test_a_whole_folder_is_moved_as_one(self):
        update = self.service.files.return_value.update
        update.return_value.execute.return_value = {'id': 'album', 'name': 'records',
                                                    'mimeType': drivecache.FOLDER_MIME_TYPE}
        self.assertEqual(self.tree.move_files([('album/track.mp3', 'records/track.mp3')]),
                         [('album/track.mp3', 'records/track.mp3')])
        update.assert_called_once_with(fileId='album', body={'name': 'records'}, addParents='mein',
                                       removeParents='mein', fields=drivecache.FILE_FIELDS)
        self.assertNotIn('album', self.tree)
        self.assertEqual(self.tree._cloud_ids['records/track.mp3'], 'track')
        found = {entry.relpath: entry.cloud_id for entry in drivecache.entries('/mein')}
        self.assertEqual(found['records/track.mp3'], 'track')
        # Nothing left empty to trash
        self.assertEqual(self.trashed(), [])

    def test_copy_within_drive_is_one_request(self):
        copy = self.service.files.return_value.copy
        copy.return_value.execute.return_value = {'id': 'copied', 'mimeType': 'audio/mpeg', 'size': '5'}
        self.assertEqual(self.tree.copy_files_within([('song.mp3', 'album/song.mp3')]),
                         [('song.mp3', 'album/song.mp3')])
        copy.assert_called_once_with(fileId='song', body={'name': 'song.mp3', 'parents': ['album']},
                                     fields=drivecache.FILE_FIELDS)
        self.assertIn('song.mp3', self.tree)
        self.assertEqual(self.tree._cloud_ids['album/song.mp3'], 'copied')
        found = {entry.relpath: entry.cloud_id for entry in drivecache.entries('/mein')}
        self.assertEqual(found['album/song.mp3'], 'copied')

    def test_move_into_a_new_folder_makes_it(self):
        self.move('song.mp3', 'new/moved.mp3')
        self.assertEqual([body['name'] for body in self.creates()], ['new'])
        self.assertIn('new/moved.mp3', self.tree)

    def test_google_files_and_same_named_ones_arent_moved(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(drive_item('sheet', 'Budget', 'mein', 'application/vnd.google-apps.spreadsheet')) + '\n')
        self.tree = clouddirtree.factory('cloud/mein')
        self.assertIsNotNone(self.tree.cant_move('Budget.gsheet'))
        dup = next(relpath for relpath in self.tree._cloud_ids if clouddirtree.DUP_SUFFIX in relpath)
        self.assertIsNotNone(self.tree.cant_move(dup))
        self.assertIsNone(self.tree.cant_move('song.mp3'))
        self.assertEqual(self.tree.move_files([('Budget.gsheet', 'x.gsheet')]), [])
        self.service.files.return_value.update.assert_not_called()

    def test_a_failed_move_keeps_the_file(self):
        self.service.files.return_value.update.return_value.execute.side_effect = http_error()
        self.assertEqual(self.tree.move_files([('song.mp3', 'moved.mp3')]), [])
        self.assertIn('song.mp3', self.tree)

    def test_dry_run_moves_nothing(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.assertEqual(self.tree.move_files([('song.mp3', 'moved.mp3')]), [])
        self.service.files.return_value.update.assert_not_called()
        self.assertIn('song.mp3', self.tree)


if __name__ == '__main__':
    unittest.main()
