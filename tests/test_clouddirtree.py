import itertools
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from googleapiclient.errors import HttpError

from dirdelta import clouddirtree
from dirdelta import dirtree
from dirdelta import entries
from dirdelta import localdiskdirtree
import helpers

FOLDER = 'application/vnd.google-apps.folder'


def _item(id, name, parent, mime='audio/mpeg'):
    return {'id': id, 'name': name, 'parents': [parent], 'mimeType': mime}


# ROOT (Drive's root, never listed itself)
# |-- mein/
# |   |-- song.mp3
# |   |-- album/track.mp3
# |   |-- dup.mp3   (two different files with the same name)
# |   `-- dup.mp3
# `-- other/elsewhere.mp3
ITEMS = [
    _item('mein', 'mein', 'ROOT', FOLDER),
    _item('song', 'song.mp3', 'mein'),
    _item('album', 'album', 'mein', FOLDER),
    _item('track', 'track.mp3', 'album'),
    _item('dup1', 'dup.mp3', 'mein'),
    _item('dup2', 'dup.mp3', 'mein'),
    _item('other', 'other', 'ROOT', FOLDER),
    _item('elsewhere', 'elsewhere.mp3', 'other'),
]


class CloudDirTreeTest(unittest.TestCase):
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-cloud-cache-')
        with os.fdopen(fd, 'w') as f:
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        patcher = mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.remove, self.cache)

    def _relpaths(self, tree):
        return sorted(entry.relpath for entry in tree.iter_files())

    def test_builds_files_under_the_requested_folder_only(self):
        tree = clouddirtree.factory('cloud/mein')
        self.assertIn('song.mp3', self._relpaths(tree))
        self.assertIn('album/track.mp3', self._relpaths(tree))
        self.assertNotIn('elsewhere.mp3', self._relpaths(tree))

    def test_folders_become_dirs_and_files_become_files(self):
        tree = clouddirtree.factory('cloud/mein')
        self.assertIsNotNone(tree.get_node('album'))
        self.assertNotIn('album', self._relpaths(tree))

    def test_same_named_files_both_kept_with_dup_suffix(self):
        tree = clouddirtree.factory('cloud/mein')
        dups = [path for path in self._relpaths(tree) if path.startswith('dup.mp3')]
        self.assertEqual(len(dups), 2)
        self.assertIn('dup.mp3', dups)

    def test_displayname_is_the_cloud_path(self):
        self.assertEqual(clouddirtree.factory('cloud/mein').displayname(), 'cloud/mein')
        self.assertEqual(clouddirtree.CloudDirTree('cloud').displayname(), 'cloud')

    def test_fullpath_is_the_path_inside_the_drive(self):
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.get_node('album/track.mp3').data.fullpath, '/mein/album/track.mp3')



def _http_error():
    return HttpError(mock.Mock(status=403, reason='Forbidden'), b'{}')


class _FakeBatch(object):
    """A batch request (service.new_batch_http_request()) that runs its requests when it's run,
    answering each to the callback"""
    def __init__(self, callback):
        self.callback = callback
        self.requests = []

    def add(self, request, request_id):
        self.requests.append((request, request_id))

    def execute(self):
        for request, request_id in self.requests:
            try:
                self.callback(request_id, request.execute(), None)
            except HttpError as error:
                self.callback(request_id, None, error)


class CloudDirTreeChangesTest(unittest.TestCase):
    """Copying into, out of and removing from cloud/mein (ITEMS), with Drive faked: nothing here
    reaches Drive"""
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-cloud-cache-')
        with os.fdopen(fd, 'w') as f:
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        # Drive's answer to each create (by what it's made with): a folder made with a generated id
        # keeps it
        created_ids = itertools.count()
        self.create_result = lambda body: {'id': body.get('id', 'new%d' % (next(created_ids),))}
        generated_ids = itertools.count()
        self.service = mock.Mock()
        files = self.service.files.return_value
        # Each create's body and execute()'s arguments
        self.executed = []
        def execute(body, **kwargs):
            self.executed.append((body, kwargs))
            return self.create_result(body)
        files.create.side_effect = lambda body, **_: mock.Mock(
            execute=lambda **kwargs: execute(body, **kwargs))
        files.generateIds.side_effect = lambda count, **_: mock.Mock(execute=lambda **_: {
            'ids': ['gen%d' % (next(generated_ids),) for _ in range(count)]})
        self.service.new_batch_http_request.side_effect = _FakeBatch
        self.local_dir = tempfile.mkdtemp(prefix='dirstuff-cloud-local-')
        for patcher in (mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache),
                        mock.patch('dirdelta.driveapi.service', return_value=self.service),
                        mock.patch('dirdelta.clouddirtree.MediaFileUpload'),
                        mock.patch('dirdelta.messages.print_line'),
                        mock.patch('dirdelta.dryrun.DRYRUN', False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(os.remove, self.cache)
        self.addCleanup(clouddirtree.drivecache.mark_fresh)
        self.addCleanup(shutil.rmtree, self.local_dir, ignore_errors=True)
        self.tree = clouddirtree.factory('cloud/mein')

    def creates(self):
        return [call.kwargs['body'] for call in self.service.files.return_value.create.call_args_list]

    def upload(self, relpaths, content='x'):
        """Upload files at relpaths (each with content) from a local dir"""
        helpers.make_files(self.local_dir, relpaths)
        for relpath in relpaths:
            with open(os.path.join(self.local_dir, relpath), 'w') as f:
                f.write(content)
        files = [entries.FileEntry(os.path.basename(relpath), relpath,
                                   os.path.join(self.local_dir, relpath))
                 for relpath in relpaths]
        self.tree.copy_inner_entries_from_dirtree(
            dirtree.DirTree.from_file_entries(files, self.local_dir))

    def lines(self):
        return [call.args[0] for call in clouddirtree.messages.print_line.call_args_list]

    def test_upload_into_an_existing_folder(self):
        self.upload(['album/new.mp3'])
        self.assertEqual(self.creates(), [{'name': 'new.mp3', 'parents': ['album']}])
        self.assertIn('album/new.mp3', self.tree)

    def test_a_small_file_is_uploaded_in_one_request_and_a_big_one_resumably(self):
        with mock.patch('dirdelta.clouddirtree.RESUMABLE_MIN_SIZE', 5):
            self.upload(['small.mp3'], content='1234')
            self.upload(['big.mp3'], content='12345')
        clouddirtree.MediaFileUpload.assert_has_calls([
            mock.call(os.path.join(self.local_dir, 'small.mp3'), resumable=False),
            mock.call(os.path.join(self.local_dir, 'big.mp3'), resumable=True)])

    def test_requests_are_retried(self):
        self.upload(['new.mp3'])
        self.assertEqual(self.executed, [({'name': 'new.mp3', 'parents': ['mein']},
                                          {'num_retries': clouddirtree.NUM_RETRIES})])

    def test_files_are_uploaded_at_once(self):
        # Each upload waits until the other is under way too
        both_under_way = threading.Barrier(2, timeout=5)
        def create_result(body):
            both_under_way.wait()
            return {'id': body['name']}
        self.create_result = create_result
        with mock.patch('dirdelta.clouddirtree.UPLOAD_THREADS', 2):
            self.upload(['1.mp3', '2.mp3'])
        self.assertIn('Copy complete: copied 2 of 2 files to cloud/mein', self.lines())

    def test_ctrl_c_starts_no_more_and_waits_for_the_uploads_under_way(self):
        def print_line(line, color=None):
            if line.startswith('Copying 3.mp3'):
                raise KeyboardInterrupt
        clouddirtree.messages.print_line.side_effect = print_line
        with mock.patch('dirdelta.clouddirtree.UPLOAD_THREADS', 2), \
                mock.patch('dirdelta.messages.note_stopped'):
            self.upload(['1.mp3', '2.mp3', '3.mp3', '4.mp3'])
        self.assertEqual(sorted(body['name'] for body in self.creates()), ['1.mp3', '2.mp3'])
        self.assertIn('2.mp3', self.tree)
        self.assertIn('Copy stopped: copied 2 of 4 files to cloud/mein', self.lines())
        # Both are in the cache
        relpaths = [entry.relpath for entry in clouddirtree.factory('cloud/mein').iter_files()]
        self.assertIn('1.mp3', relpaths)
        self.assertFalse(clouddirtree.drivecache.is_stale())

    def test_changes_are_kept_in_the_cache(self):
        self.upload(['a/b/new.mp3'])
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        # Read anew from the cache, as the next run would
        relpaths = sorted(entry.relpath for entry in clouddirtree.factory('cloud/mein').iter_files())
        self.assertIn('a/b/new.mp3', relpaths)
        self.assertNotIn('song.mp3', relpaths)
        self.assertIsNotNone(clouddirtree.factory('cloud/mein').get_node('a/b'))
        self.assertFalse(clouddirtree.drivecache.is_stale())

    def test_what_drive_says_of_a_new_file_is_kept(self):
        self.create_result = lambda body: {'id': 'x', 'mimeType': 'audio/mpeg', 'size': '3'}
        self.upload(['new.mp3'])
        with open(self.cache) as f:
            last = json.loads(f.readlines()[-1])
        self.assertEqual(last, {'id': 'x', 'name': 'new.mp3', 'parents': ['mein'],
                                'mimeType': 'audio/mpeg', 'size': '3'})
        create = self.service.files.return_value.create
        self.assertEqual(create.call_args.kwargs['fields'], clouddirtree.drivecache.FILE_FIELDS)

    def test_a_change_cut_off_leaves_the_cache_stale(self):
        # E.g. Ctrl-C again while waiting for the uploads under way: Drive may have them or not
        def print_line(line, color=None):
            if line.startswith('Waiting for') or line.startswith('Copying 2.mp3'):
                raise KeyboardInterrupt
        clouddirtree.messages.print_line.side_effect = print_line
        never = threading.Event()
        self.addCleanup(never.set)
        self.create_result = lambda body: never.wait(5) and {'id': 'late'}
        with mock.patch('dirdelta.clouddirtree.UPLOAD_THREADS', 2), \
                mock.patch('dirdelta.messages.note_stopped'):
            self.upload(['1.mp3', '2.mp3'])
        self.assertNotIn('1.mp3', self.tree)
        self.assertTrue(clouddirtree.drivecache.is_stale())
        # And the next change, done, doesn't make it look fresh
        never.set()
        clouddirtree.messages.print_line.side_effect = None
        self.create_result = lambda body: {'id': 'ok'}
        self.upload(['other.mp3'])
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.assertTrue(clouddirtree.drivecache.is_stale())

    def test_a_failed_change_leaves_the_cache_as_it_was(self):
        self.service.files.return_value.update.return_value.execute.side_effect = _http_error()
        with open(self.cache) as f:
            before = f.read()
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        with open(self.cache) as f:
            self.assertEqual(f.read(), before)

    def test_a_dry_run_leaves_the_cache_fresh(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.upload(['new.mp3'])
            self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.assertFalse(clouddirtree.drivecache.is_stale())

    def test_upload_into_the_root(self):
        self.upload(['new.mp3'])
        self.assertEqual(self.creates(), [{'name': 'new.mp3', 'parents': ['mein']}])

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

    def test_each_level_of_folders_is_one_batch(self):
        self.upload(['a/x/1.mp3', 'b/y/2.mp3', 'c/3.mp3'])
        self.assertEqual(self.service.new_batch_http_request.call_count, 2)
        self.service.files.return_value.generateIds.assert_called_once_with(count=5, space='drive')

    def test_big_levels_are_split_into_batches(self):
        with mock.patch('dirdelta.clouddirtree.MAX_BATCH_SIZE', 2):
            self.upload(['a/1.mp3', 'b/2.mp3', 'c/3.mp3'])
        self.assertEqual(self.service.new_batch_http_request.call_count, 2)
        self.assertEqual(len([body for body in self.creates() if 'id' in body]), 3)

    def test_a_folder_that_cant_be_made_in_a_batch_is_made_with_its_files(self):
        is_first = [True]
        def create_result(body):
            if body.get('name') == 'a' and is_first[0]:
                is_first[0] = False
                raise _http_error()
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
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.upload(['new.mp3'])
        self.service.files.return_value.create.assert_not_called()
        self.assertNotIn('new.mp3', self.tree)

    def test_a_failed_upload_is_said_and_the_rest_go_on(self):
        def create_result(body):
            if body['name'] == 'bad.mp3':
                raise _http_error()
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

    def test_remove_moves_to_the_trash(self):
        self.tree.remove_files([self.tree.get_node('album/track.mp3').data])
        self.service.files.return_value.update.assert_called_once_with(fileId='track',
                                                                       body={'trashed': True})
        self.assertNotIn('album/track.mp3', self.tree)
        lines = [call.args[0] for call in clouddirtree.messages.print_line.call_args_list]
        self.assertIn("Remove complete: removed 1 of 1 files from cloud/mein (to Drive's trash)", lines)

    def test_dry_run_removes_nothing(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.service.files.return_value.update.assert_not_called()
        self.assertIn('song.mp3', self.tree)

    def test_a_failed_remove_keeps_the_file(self):
        self.service.files.return_value.update.return_value.execute.side_effect = _http_error()
        self.tree.remove_files([self.tree.get_node('song.mp3').data])
        self.assertIn('song.mp3', self.tree)

    def download_to_local_dir(self, relpaths):
        local = localdiskdirtree.LocalDiskDirTree(self.local_dir, silent=True)
        files = [self.tree.get_node(relpath).data for relpath in relpaths]
        local.copy_inner_entries_from_dirtree(dirtree.DirTree.from_file_entries(files, '/mein'),
                                              self.tree)
        return local

    def test_download(self):
        def downloader(local_file, request):
            local_file.write(b'track content')
            return mock.Mock(next_chunk=mock.Mock(return_value=(None, True)))
        with mock.patch('dirdelta.clouddirtree.MediaIoBaseDownload', side_effect=downloader):
            local = self.download_to_local_dir(['album/track.mp3'])
        self.service.files.return_value.get_media.assert_called_once_with(fileId='track')
        with open(os.path.join(self.local_dir, 'album', 'track.mp3'), 'rb') as f:
            self.assertEqual(f.read(), b'track content')
        self.assertIn('album/track.mp3', local)

    def test_a_failed_download_leaves_no_file_and_the_rest_go_on(self):
        def downloader(local_file, request):
            local_file.write(b'part of it')
            return mock.Mock(next_chunk=mock.Mock(side_effect=_http_error()))
        with mock.patch('dirdelta.clouddirtree.MediaIoBaseDownload', side_effect=downloader):
            local = self.download_to_local_dir(['song.mp3', 'album/track.mp3'])
        self.assertEqual(os.listdir(self.local_dir), ['album'])
        self.assertEqual(os.listdir(os.path.join(self.local_dir, 'album')), [])
        self.assertNotIn('song.mp3', local)


if __name__ == '__main__':
    unittest.main()
