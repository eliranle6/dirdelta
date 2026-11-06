"""Copying files into a Drive tree: uploads, the folders made for them, and the cache"""
import os
import threading
import unittest
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from dirdelta.trees import dirtree
from dirdelta.trees import entries
from dirdelta.ui import messages
from clouddirtree_support import CloudDirTreeChangesTest, FOLDER, http_error


class UploadsTest(CloudDirTreeChangesTest):
    """Uploads"""

    def test_upload_into_an_existing_folder(self):
        self.upload(['album/new.mp3'])
        self.assertEqual(self.creates(), [{'name': 'new.mp3', 'parents': ['album']}])
        self.assertIn('album/new.mp3', self.tree)

    def test_a_file_is_uploaded_from_its_own_path_whatever_its_relpath(self):
        # E.g. an inbox's file going to another dir of the sorted tree
        helpers.make_files(self.local_dir, ['inbox/a.mp3'])
        self.tree.copy_in([entries.FileEntry('a.mp3', 'album/a.mp3', os.path.join(self.local_dir, 'inbox/a.mp3'))])
        self.assertEqual(self.creates(), [{'name': 'a.mp3', 'parents': ['album']}])
        clouddirtree.uploads.MediaFileUpload.assert_called_once_with(os.path.join(self.local_dir, 'inbox/a.mp3'),
                                                             resumable=False)

    def test_an_upload_keeps_its_time(self):
        helpers.make_files(self.local_dir, ['new.mp3'])
        os.utime(os.path.join(self.local_dir, 'new.mp3'), (1719842602, 1719842602))
        self.tree.copy_inner_entries_from_dirtree(dirtree.DirTree.from_file_entries(
            [entries.FileEntry('new.mp3', 'new.mp3', os.path.join(self.local_dir, 'new.mp3'))], self.local_dir))
        self.assertEqual(self.creates(with_times=True)[0]['modifiedTime'], '2024-07-01T14:03:22.000000Z')

    def test_a_small_file_is_uploaded_in_one_request_and_a_big_one_resumably(self):
        with mock.patch('dirdelta.drive.clouddirtree.uploads.RESUMABLE_MIN_SIZE', 5):
            self.upload(['small.mp3'], content='1234')
            self.upload(['big.mp3'], content='12345')
        clouddirtree.uploads.MediaFileUpload.assert_has_calls([
            mock.call(os.path.join(self.local_dir, 'small.mp3'), resumable=False),
            mock.call(os.path.join(self.local_dir, 'big.mp3'), resumable=True)])

    def test_files_are_uploaded_at_once(self):
        # Each upload waits until the other is under way too
        # (A timeout long enough for a loaded machine: it only matters if the uploads aren't at once)
        both_under_way = threading.Barrier(2, timeout=30)
        def create_result(body):
            both_under_way.wait()
            return {'id': body['name']}
        self.create_result = create_result
        with mock.patch('dirdelta.drive.clouddirtree.uploads.UPLOAD_THREADS', 2):
            self.upload(['1.mp3', '2.mp3'])
        self.assertIn('Copy complete: copied 2 of 2 files to cloud/mein', self.lines())

    def test_ctrl_c_starts_no_more_and_waits_for_the_uploads_under_way(self):
        def print_line(line, color=None):
            if line.startswith('Copying 3.mp3'):
                raise KeyboardInterrupt
        messages.print_line.side_effect = print_line
        with mock.patch('dirdelta.drive.clouddirtree.uploads.UPLOAD_THREADS', 2), \
                mock.patch('dirdelta.ui.messages.note_stopped'):
            self.upload(['1.mp3', '2.mp3', '3.mp3', '4.mp3'])
        self.assertEqual(sorted(body['name'] for body in self.creates()), ['1.mp3', '2.mp3'])
        self.assertIn('2.mp3', self.tree)
        self.assertIn('Copy stopped: copied 2 of 4 files to cloud/mein', self.lines())
        # Both are in the cache
        relpaths = [entry.relpath for entry in clouddirtree.factory('cloud/mein').iter_files()]
        self.assertIn('1.mp3', relpaths)
        self.assertFalse(drivecache.stale_paths())

    def test_a_copy_replacing_a_file_makes_a_new_version_of_it(self):
        files = self.service.files.return_value
        files.update.side_effect = lambda **kwargs: mock.Mock(execute=lambda **_: {
            'id': kwargs['fileId'], 'name': 'song.mp3', 'size': '7', 'sha1Checksum': 'abc'})
        removed = []
        self.tree.add_listener(mock.Mock(remove=removed.append))
        with self.tree.replacing():
            self.upload(['song.mp3', 'album/new.mp3'])
        # The one there gets the copy as its new version (Drive keeps the old one); the other is made
        self.assertEqual(files.update.call_args.kwargs['fileId'], 'song')
        self.assertEqual(set(files.update.call_args.kwargs['body']), {'modifiedTime'})
        self.assertEqual(self.creates(), [{'name': 'new.mp3', 'parents': ['album']}])
        self.assertEqual(removed, ['song.mp3'])
        self.assertEqual(self.tree.file_size('song.mp3'), 7)
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.file_size('song.mp3'), 7)
        self.assertEqual(sorted(entry.relpath for entry in tree.iter_files() if entry.relpath.startswith('song')),
                         ['song.mp3'])

    def test_writing_a_file_there_makes_a_new_version_of_it(self):
        files = self.service.files.return_value
        files.update.side_effect = lambda **kwargs: mock.Mock(execute=lambda **_: {
            'id': kwargs['fileId'], 'name': 'song.mp3', 'size': '7', 'sha1Checksum': 'abc'})
        self.tree.write_file('song.mp3', os.path.join(self.local_dir, 'new'))
        self.assertEqual(files.update.call_args.kwargs['fileId'], 'song')
        clouddirtree.uploads.MediaFileUpload.assert_called_with(os.path.join(self.local_dir, 'new'))
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.tree.file_size('song.mp3'), 7)
        # In the cache, in its folder still
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.file_size('song.mp3'), 7)
        self.assertFalse(drivecache.stale_paths())

    def test_writing_a_file_that_isnt_there_makes_it(self):
        helpers.make_files(self.local_dir, ['last_update.txt'])
        self.tree.write_file('last_update.txt', os.path.join(self.local_dir, 'last_update.txt'))
        self.assertEqual(self.creates(), [{'name': 'last_update.txt', 'parents': ['mein']}])
        self.assertIn('last_update.txt', [entry.relpath for entry in clouddirtree.factory('cloud/mein').iter_files()])

    def test_changes_are_kept_in_the_cache(self):
        self.upload(['a/b/new.mp3'])
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        # Read anew from the cache, as the next run would
        relpaths = sorted(entry.relpath for entry in clouddirtree.factory('cloud/mein').iter_files())
        self.assertIn('a/b/new.mp3', relpaths)
        self.assertNotIn('song.mp3', relpaths)
        self.assertIsNotNone(clouddirtree.factory('cloud/mein').get_node('a/b'))
        self.assertFalse(drivecache.stale_paths())

    def test_what_drive_says_of_a_new_file_is_kept(self):
        self.create_result = lambda body: {'id': 'x', 'mimeType': 'audio/mpeg', 'size': '3'}
        self.upload(['new.mp3'])
        last = drivecache.rows()[-1]
        # With the modification time it was made with
        self.assertTrue(last.pop('modifiedTime'))
        self.assertEqual(last, {'id': 'x', 'name': 'new.mp3', 'parents': ['mein'],
                                'mimeType': 'audio/mpeg', 'size': '3'})
        create = self.service.files.return_value.create
        self.assertEqual(create.call_args.kwargs['fields'], drivecache.FILE_FIELDS)

    def test_a_change_cut_off_leaves_the_cache_stale(self):
        # E.g. Ctrl-C again while waiting for the uploads under way: Drive may have them or not
        def print_line(line, color=None):
            if line.startswith('Waiting for') or line.startswith('Copying 2.mp3'):
                raise KeyboardInterrupt
        messages.print_line.side_effect = print_line
        never, ended = threading.Event(), threading.Event()
        self.addCleanup(never.set)

        def late(body):
            # The upload under way, cut off: it ends after the test says so (never on its own)
            never.wait(30)
            ended.set()
            return {'id': 'late'}
        self.create_result = late
        with mock.patch('dirdelta.drive.clouddirtree.uploads.UPLOAD_THREADS', 2), \
                mock.patch('dirdelta.ui.messages.note_stopped'):
            self.upload(['1.mp3', '2.mp3'])
        self.assertNotIn('1.mp3', self.tree)
        self.assertTrue(drivecache.stale_paths())
        # And the next change, done, doesn't make it look fresh
        never.set()
        # Its thread is done before the next change, so nothing of it overlaps that
        self.assertTrue(ended.wait(30))
        messages.print_line.side_effect = None
        self.create_result = lambda body: {'id': 'ok'}
        self.upload(['other.mp3'])
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.assertTrue(drivecache.stale_paths())

    def test_a_failed_change_leaves_the_cache_as_it_was(self):
        self.service.files.return_value.update.return_value.execute.side_effect = http_error()
        before = drivecache.rows()
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.assertEqual(drivecache.rows(), before)
        # Nothing changed in Drive: not stale (asking for a refresh) either
        self.assertFalse(drivecache.stale_paths())

    def test_upload_makes_the_folders_its_in_first_once(self):
        self.upload(['a/b/1.mp3', 'a/b/2.mp3', 'a/3.mp3'])
        creates = self.creates()
        self.assertEqual(creates[:2], [
            {'id': 'gen0', 'name': 'a', 'mimeType': FOLDER, 'parents': ['mein']},
            {'id': 'gen1', 'name': 'b', 'mimeType': FOLDER, 'parents': ['gen0']},
        ])
        self.assertCountEqual(creates[2:], [
            {'name': '1.mp3', 'parents': ['gen1']},
            {'name': '2.mp3', 'parents': ['gen1']},
            {'name': '3.mp3', 'parents': ['gen0']},
        ])
        self.assertIn('a/b/2.mp3', self.tree)
        # In the cache too
        self.assertIsNotNone(clouddirtree.factory('cloud/mein').get_node('a/b'))

    def test_big_levels_are_split_into_batches(self):
        with mock.patch('dirdelta.drive.clouddirtree.folders.MAX_BATCH_SIZE', 2):
            self.upload(['a/1.mp3', 'b/2.mp3', 'c/3.mp3'])
        self.assertEqual(self.service.new_batch_http_request.call_count, 2)
        self.assertEqual(len([body for body in self.creates() if 'id' in body]), 3)

    def test_a_folder_that_cant_be_made_in_a_batch_is_made_with_its_files(self):
        is_first = [True]
        def create_result(body):
            if body.get('name') == 'a' and is_first[0]:
                is_first[0] = False
                raise http_error()
            return {'id': body.get('id', 'made-' + body['name'])}
        self.create_result = create_result
        self.upload(['a/b/1.mp3'])
        self.assertIn('a/b/1.mp3', self.tree)
        # b's parent wasn't there to make it in its batch: both were made one by one
        self.assertEqual([body for body in self.creates() if 'id' not in body], [
            {'name': 'a', 'mimeType': FOLDER, 'parents': ['mein']},
            {'name': 'b', 'mimeType': FOLDER, 'parents': ['made-a']},
            {'name': '1.mp3', 'parents': ['made-b']},
        ])
        self.assertTrue(any(line.startswith("Couldn't make folder a") for line in self.lines()))

    def test_dry_run_uploads_nothing(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.upload(['new.mp3'])
        self.service.files.return_value.create.assert_not_called()
        self.assertNotIn('new.mp3', self.tree)

    def test_a_failed_upload_is_said_and_the_rest_go_on(self):
        def create_result(body):
            if body['name'] == 'bad.mp3':
                raise http_error()
            return {'id': 'ok'}
        self.create_result = create_result
        self.upload(['bad.mp3', 'good.mp3'])
        self.assertNotIn('bad.mp3', self.tree)
        self.assertIn('good.mp3', self.tree)
        self.assertTrue(any(line.startswith('Copy failed') for line in self.lines()))
        self.assertIn('Copy complete: copied 1 of 2 files to cloud/mein', self.lines())

    def test_a_file_that_cant_be_read_is_said_and_the_rest_go_on(self):
        files = [entries.FileEntry('gone.mp3', 'gone.mp3', os.path.join(self.local_dir, 'gone.mp3'))]
        self.tree.copy_inner_entries_from_dirtree(
            dirtree.DirTree.from_file_entries(files, self.local_dir))
        self.assertNotIn('gone.mp3', self.tree)
        self.assertTrue(any(line.startswith('Copy failed') for line in self.lines()))


if __name__ == '__main__':
    unittest.main()
