import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from googleapiclient.errors import HttpError

from dirdelta import clouddirtree
from dirdelta import dirtree
from dirdelta import entries
from dirdelta import localdiskdirtree

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

    def test_fullpath_is_the_path_inside_the_drive(self):
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.get_node('album/track.mp3').data.fullpath, '/mein/album/track.mp3')



def _http_error():
    return HttpError(mock.Mock(status=403, reason='Forbidden'), b'{}')


class CloudDirTreeChangesTest(unittest.TestCase):
    """Copying into, out of and removing from cloud/mein (ITEMS), with Drive faked: nothing here
    reaches Drive"""
    def setUp(self):
        fd, self.cache = tempfile.mkstemp(prefix='dirstuff-cloud-cache-')
        with os.fdopen(fd, 'w') as f:
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        self.service = mock.Mock()
        created_ids = iter('new%d' % (i,) for i in range(100))
        self.service.files.return_value.create.return_value.execute.side_effect = \
            lambda: {'id': next(created_ids)}
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

    def upload(self, relpaths):
        files = [entries.FileEntry(os.path.basename(relpath), relpath, os.path.join('/local', relpath))
                 for relpath in relpaths]
        self.tree.copy_inner_entries_from_dirtree(dirtree.DirTree.from_file_entries(files, '/local'))

    def test_upload_into_an_existing_folder(self):
        self.upload(['album/new.mp3'])
        self.assertEqual(self.creates(), [{'name': 'new.mp3', 'parents': ['album']}])
        clouddirtree.MediaFileUpload.assert_called_once_with('/local/album/new.mp3', resumable=True)
        self.assertIn('album/new.mp3', self.tree)

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
        self.service.files.return_value.create.return_value.execute.side_effect = \
            lambda: {'id': 'x', 'mimeType': 'audio/mpeg', 'size': '3'}
        self.upload(['new.mp3'])
        with open(self.cache) as f:
            last = json.loads(f.readlines()[-1])
        self.assertEqual(last, {'id': 'x', 'name': 'new.mp3', 'parents': ['mein'],
                                'mimeType': 'audio/mpeg', 'size': '3'})
        create = self.service.files.return_value.create
        self.assertEqual(create.call_args.kwargs['fields'], clouddirtree.drivecache.FILE_FIELDS)

    def test_a_change_cut_off_leaves_the_cache_stale(self):
        # E.g. Ctrl-C while uploading: Drive may have the file or not
        self.service.files.return_value.create.return_value.execute.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.tree._copy_file(entries.FileEntry('new.mp3', 'new.mp3', '/local/new.mp3'), None)
        self.assertTrue(clouddirtree.drivecache.is_stale())
        # And the next change, done, doesn't make it look fresh
        self.service.files.return_value.create.return_value.execute.side_effect = \
            lambda: {'id': 'ok'}
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

    def test_upload_makes_the_folders_its_in_once(self):
        self.upload(['a/b/1.mp3', 'a/b/2.mp3'])
        self.assertEqual(self.creates(), [
            {'name': 'a', 'mimeType': clouddirtree.drivecache.FOLDER_MIME_TYPE, 'parents': ['mein']},
            {'name': 'b', 'mimeType': clouddirtree.drivecache.FOLDER_MIME_TYPE, 'parents': ['new0']},
            {'name': '1.mp3', 'parents': ['new1']},
            {'name': '2.mp3', 'parents': ['new1']},
        ])
        self.assertIn('a/b/2.mp3', self.tree)

    def test_dry_run_uploads_nothing(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.upload(['new.mp3'])
        self.service.files.return_value.create.assert_not_called()
        self.assertNotIn('new.mp3', self.tree)

    def test_a_failed_upload_is_said_and_the_rest_go_on(self):
        results = iter([_http_error(), {'id': 'ok'}])
        def execute():
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return result
        self.service.files.return_value.create.return_value.execute.side_effect = execute
        self.upload(['bad.mp3', 'good.mp3'])
        self.assertNotIn('bad.mp3', self.tree)
        self.assertIn('good.mp3', self.tree)
        lines = [call.args[0] for call in clouddirtree.messages.print_line.call_args_list]
        self.assertTrue(any(line.startswith('Copy failed') for line in lines))
        self.assertIn('Copy complete: copied 1 of 2 files to /mein', lines)

    def test_remove_moves_to_the_trash(self):
        self.tree.remove_files([self.tree.get_node('album/track.mp3').data])
        self.service.files.return_value.update.assert_called_once_with(fileId='track',
                                                                       body={'trashed': True})
        self.assertNotIn('album/track.mp3', self.tree)
        lines = [call.args[0] for call in clouddirtree.messages.print_line.call_args_list]
        self.assertIn("Remove complete: removed 1 of 1 files from /mein (to Drive's trash)", lines)

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
