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

    def google_tree(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(_item('sheet', 'Budget', 'mein', 'application/vnd.google-apps.spreadsheet')) + '\n')
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
        # What Drive lists for a query (what's in some folders), beyond what the cache has
        self.listed = lambda query: []
        files.list.side_effect = lambda q, **_: mock.Mock(
            execute=lambda **_: {'files': self.listed(q)})
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

    def remove(self, relpaths):
        self.tree.remove_files([self.tree.get_node(relpath).data for relpath in relpaths])

    def trashed(self):
        return [call.kwargs['fileId'] for call in self.service.files.return_value.update.call_args_list]

    def add(self, relpath, cloud_id):
        """Add a file to the tree (and the dirs it's in, each with its name as its id)"""
        self.tree.add_file_by_relpath(relpath)
        self.tree._cloud_ids[relpath] = cloud_id
        dirpath = os.path.dirname(relpath)
        while dirpath:
            self.tree._cloud_ids.setdefault(dirpath, os.path.basename(dirpath))
            dirpath = os.path.dirname(dirpath)

    def test_remove_moves_to_the_trash(self):
        self.remove(['song.mp3'])
        self.service.files.return_value.update.assert_called_once_with(fileId='song',
                                                                       body={'trashed': True})
        self.assertNotIn('song.mp3', self.tree)
        self.assertIn("Remove complete: removed 1 of 1 files from cloud/mein (to Drive's trash)",
                      self.lines())

    def test_a_folder_all_of_whose_files_are_removed_is_trashed_as_one(self):
        self.remove(['album/track.mp3'])
        self.assertEqual(self.trashed(), ['album'])
        self.assertNotIn('album', self.tree)
        self.assertIn('Removing folder album/ and its 1 files (1 out of 1)', self.lines())
        self.assertIn("Remove complete: removed 1 of 1 files from cloud/mein (to Drive's trash)",
                      self.lines())
        # The cache has it trashed, and what's in it
        self.assertIsNone(clouddirtree.factory('cloud/mein').get_node('album'))
        self.assertFalse(clouddirtree.drivecache.is_stale())

    def test_only_the_topmost_whole_folders_are_trashed(self):
        for relpath, cloud_id in (('a/1.mp3', 'one'), ('a/b/2.mp3', 'two'), ('a/b/c/3.mp3', 'three'),
                                  ('d/4.mp3', 'four'), ('d/e/5.mp3', 'five')):
            self.add(relpath, cloud_id)
        self.remove(['a/1.mp3', 'a/b/2.mp3', 'a/b/c/3.mp3', 'd/e/5.mp3'])
        # d keeps 4.mp3, so only d/e goes whole
        self.assertCountEqual(self.trashed(), ['a', 'e'])
        self.assertIn('d/4.mp3', self.tree)

    def test_a_folder_with_a_file_not_picked_is_kept(self):
        # The picker didn't show it: the other replica has it too
        self.add('album/also-elsewhere.mp3', 'elsewhere')
        self.remove(['album/track.mp3'])
        self.assertEqual(self.trashed(), ['track'])
        self.assertIn('album/also-elsewhere.mp3', self.tree)
        self.service.files.return_value.list.assert_not_called()

    def test_files_at_the_root_are_trashed_one_by_one_not_the_root(self):
        self.remove(['song.mp3', 'album/track.mp3', 'dup.mp3', 'dup.mp3___DUP__dup2'])
        self.assertCountEqual(self.trashed(), ['song', 'album', 'dup1', 'dup2'])

    def test_drive_is_asked_whats_in_the_folders_first(self):
        self.add('a/b/1.mp3', 'one')
        self.remove(['a/b/1.mp3'])
        query = self.service.files.return_value.list.call_args.kwargs['q']
        self.assertIn("'a' in parents", query)
        self.assertIn("'b' in parents", query)
        self.assertIn('trashed = false', query)

    def test_a_folder_that_drive_has_more_in_is_kept(self):
        # Since the cache was made, a file was added to a/b in Drive
        for relpath, cloud_id in (('a/1.mp3', 'one'), ('a/b/2.mp3', 'two'), ('a/c/3.mp3', 'three')):
            self.add(relpath, cloud_id)
        self.listed = lambda query: ([{'id': 'new', 'parents': ['b']}]
                                     if "'b' in parents" in query else [])
        self.remove(['a/1.mp3', 'a/b/2.mp3', 'a/c/3.mp3'])
        # a and b are kept; c goes whole, and the others one by one
        self.assertCountEqual(self.trashed(), ['c', 'one', 'two'])
        self.assertIn('a/b', self.tree)
        self.assertTrue(any(line.startswith('Drive has files in 1 folders') for line in self.lines()))

    def test_if_drive_cant_be_asked_the_files_are_trashed_one_by_one(self):
        def listed(query):
            raise _http_error()
        self.listed = listed
        self.remove(['album/track.mp3'])
        self.assertEqual(self.trashed(), ['track'])

    def test_many_folders_are_asked_about_in_a_few_queries(self):
        for i in range(5):
            self.add('f%d/x.mp3' % (i,), 'x%d' % (i,))
        with mock.patch('dirdelta.clouddirtree.MAX_FOLDERS_PER_QUERY', 2):
            self.remove(['f%d/x.mp3' % (i,) for i in range(5)])
        self.assertEqual(self.service.files.return_value.list.call_count, 3)
        self.assertEqual(len(self.trashed()), 5)

    def test_a_dry_run_says_which_folders_it_would_trash(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.remove(['album/track.mp3', 'song.mp3'])
        self.service.files.return_value.update.assert_not_called()
        self.service.files.return_value.list.assert_not_called()
        self.assertIn('Dry run, not removing folder album/ and its 1 files (1 out of 2)', self.lines())
        self.assertIn('album', self.tree)

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

    def test_a_google_file_isnt_copied_to_a_dir_and_the_rest_are(self):
        self.tree.add_file_by_relpath('Budget.gsheet')
        self.tree._cloud_ids['Budget.gsheet'] = 'sheet'
        self.tree._google_files.add('Budget.gsheet')
        def downloader(local_file, request):
            local_file.write(b'content')
            return mock.Mock(next_chunk=mock.Mock(return_value=(None, True)))
        with mock.patch('dirdelta.clouddirtree.MediaIoBaseDownload', side_effect=downloader):
            local = self.download_to_local_dir(['Budget.gsheet', 'song.mp3'])
        self.assertEqual(os.listdir(self.local_dir), ['song.mp3'])
        self.assertNotIn('Budget.gsheet', local)
        self.assertTrue(any(line.startswith('Skipped Budget.gsheet') for line in self.lines()))
        self.assertIn('Copy complete: copied 1 of 2 files to %s' % (os.path.realpath(self.local_dir),),
                      self.lines())

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
