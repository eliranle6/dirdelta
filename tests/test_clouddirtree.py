import itertools
import json
import os
import re
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

    def test_file_sizes_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(_item('sized', 'sized.mp3', 'mein'), size='1234')) + '\n')
        tree = self.google_tree()
        self.assertEqual(tree.file_size('sized.mp3'), 1234)
        self.assertIsNone(tree.file_size('song.mp3'))
        self.assertIsNone(tree.file_size('Budget.gsheet'))

    def test_modification_times_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(_item('t', 't.mp3', 'mein'), modifiedTime='2024-07-01T14:03:22.000Z')) + '\n')
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.modified_time('t.mp3'), 1719842602)
        self.assertIsNone(tree.modified_time('song.mp3'))

    def test_dates_taken_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(_item('photo', 'x.jpg', 'mein', 'image/jpeg'),
                                    imageMediaMetadata={'time': '2024:07:01 14:03:22'})) + '\n')
        tree = clouddirtree.factory('cloud/mein')
        self.assertEqual(tree.date_taken('x.jpg'), '2024-07-01 14:03:22')
        self.assertIsNone(tree.date_taken('song.mp3'))

    def test_hashes_are_the_caches(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(dict(_item('h', 'h.mp3', 'mein'), sha1Checksum='S1', sha256Checksum='S256')) + '\n')
            f.write(json.dumps(dict(_item('old', 'old.mp3', 'mein'), sha256Checksum='O256')) + '\n')
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
            # Without an upload's modification time, which is now (see test_an_upload_keeps_its_time)
            self.executed.append(({key: value for key, value in body.items() if key != 'modifiedTime'},
                                  kwargs))
            return self.create_result(body)
        files.create.side_effect = lambda body, **_: mock.Mock(
            execute=lambda **kwargs: execute(body, **kwargs))
        files.generateIds.side_effect = lambda count, **_: mock.Mock(execute=lambda **_: {
            'ids': ['gen%d' % (next(generated_ids),) for _ in range(count)]})
        self.service.new_batch_http_request.side_effect = _FakeBatch
        # My Drive's root folder
        files.get.return_value.execute.return_value = {'id': 'ROOT'}
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

    def creates(self, with_times=False):
        """What each create was made with (without an upload's modification time, unless with_times)"""
        return [{key: value for key, value in call.kwargs['body'].items()
                 if with_times or key != 'modifiedTime'}
                for call in self.service.files.return_value.create.call_args_list]

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

    def test_an_upload_keeps_its_time(self):
        helpers.make_files(self.local_dir, ['new.mp3'])
        os.utime(os.path.join(self.local_dir, 'new.mp3'), (1719842602, 1719842602))
        self.tree.copy_inner_entries_from_dirtree(dirtree.DirTree.from_file_entries(
            [entries.FileEntry('new.mp3', 'new.mp3', os.path.join(self.local_dir, 'new.mp3'))], self.local_dir))
        self.assertEqual(self.creates(with_times=True)[0]['modifiedTime'], '2024-07-01T14:03:22.000000Z')

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
        # With the modification time it was made with
        self.assertTrue(last.pop('modifiedTime'))
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
        return [call.kwargs['fileId'] for call in self.service.files.return_value.update.call_args_list
                if call.kwargs.get('body') == {'trashed': True}]

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

    def move(self, relpath, new_relpath):
        update = self.service.files.return_value.update
        update.return_value.execute.return_value = {
            'id': self.tree._cloud_ids[relpath], 'name': os.path.basename(new_relpath),
            'mimeType': 'audio/mpeg', 'size': '5'}
        return self.tree.move_files([(relpath, new_relpath)])

    def test_move_renames_and_reparents_the_file_in_drive(self):
        self.assertEqual(self.move('song.mp3', 'album/moved.mp3'), [('song.mp3', 'album/moved.mp3')])
        update = self.service.files.return_value.update
        update.assert_called_once_with(fileId='song', body={'name': 'moved.mp3'}, addParents='album',
                                       removeParents='mein', fields=clouddirtree.drivecache.FILE_FIELDS)
        self.assertNotIn('song.mp3', self.tree)
        self.assertEqual(self.tree._cloud_ids['album/moved.mp3'], 'song')
        # The cache has it at its new path, by the same id
        found = {entry.relpath: entry.cloud_id for entry in clouddirtree.drivecache.entries('/mein')}
        self.assertEqual(found['album/moved.mp3'], 'song')
        self.assertNotIn('song.mp3', found)
        self.assertFalse(clouddirtree.drivecache.is_stale())
        self.assertIn('Move complete: moved 1 of 1 files in cloud/mein', self.lines())

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
                                                    'mimeType': clouddirtree.drivecache.FOLDER_MIME_TYPE}
        self.assertEqual(self.tree.move_files([('album/track.mp3', 'records/track.mp3')]),
                         [('album/track.mp3', 'records/track.mp3')])
        update.assert_called_once_with(fileId='album', body={'name': 'records'}, addParents='mein',
                                       removeParents='mein', fields=clouddirtree.drivecache.FILE_FIELDS)
        self.assertNotIn('album', self.tree)
        self.assertEqual(self.tree._cloud_ids['records/track.mp3'], 'track')
        found = {entry.relpath: entry.cloud_id for entry in clouddirtree.drivecache.entries('/mein')}
        self.assertEqual(found['records/track.mp3'], 'track')
        # Nothing left empty to trash
        self.assertEqual(self.trashed(), [])

    def test_move_into_a_new_folder_makes_it(self):
        self.move('song.mp3', 'new/moved.mp3')
        self.assertEqual([body['name'] for body in self.creates()], ['new'])
        self.assertIn('new/moved.mp3', self.tree)

    def test_google_files_and_same_named_ones_arent_moved(self):
        with open(self.cache, 'a') as f:
            f.write(json.dumps(_item('sheet', 'Budget', 'mein', 'application/vnd.google-apps.spreadsheet')) + '\n')
        self.tree = clouddirtree.factory('cloud/mein')
        self.assertIsNotNone(self.tree.cant_move('Budget.gsheet'))
        dup = next(relpath for relpath in self.tree._cloud_ids if clouddirtree.DUP_SUFFIX in relpath)
        self.assertIsNotNone(self.tree.cant_move(dup))
        self.assertIsNone(self.tree.cant_move('song.mp3'))
        self.assertEqual(self.tree.move_files([('Budget.gsheet', 'x.gsheet')]), [])
        self.service.files.return_value.update.assert_not_called()

    def test_a_failed_move_keeps_the_file(self):
        self.service.files.return_value.update.return_value.execute.side_effect = _http_error()
        self.assertEqual(self.tree.move_files([('song.mp3', 'moved.mp3')]), [])
        self.assertIn('song.mp3', self.tree)

    def test_dry_run_moves_nothing(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.assertEqual(self.tree.move_files([('song.mp3', 'moved.mp3')]), [])
        self.service.files.return_value.update.assert_not_called()
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

    def test_a_download_gets_drives_modification_time(self):
        self.tree._modified['album/track.mp3'] = 1719842602
        def downloader(local_file, request):
            local_file.write(b'track content')
            return mock.Mock(next_chunk=mock.Mock(return_value=(None, True)))
        with mock.patch('dirdelta.clouddirtree.MediaIoBaseDownload', side_effect=downloader):
            self.download_to_local_dir(['album/track.mp3'])
        self.assertEqual(os.path.getmtime(os.path.join(self.local_dir, 'album', 'track.mp3')), 1719842602)

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

    def relpaths(self, tree):
        return sorted(entry.relpath for entry in tree.iter_files())

    def drive_has(self, items):
        """Make Drive list items (as what's in their parent folders, or by name in one)"""
        def listed(query):
            match = re.match(r"name = '((?:[^'\\\\]|\\\\.)*)' and '([^']*)' in parents", query)
            if match:
                name = re.sub(r"\\\\(.)", r"\1", match.group(1))
                return [md for md in items if md['name'] == name and match.group(2) in md['parents']
                        and md.get('mimeType') == FOLDER]
            return [md for md in items
                    if any("'%s' in parents" % (parent,) in query for parent in md['parents'])]
        self.listed = listed

    # Drive now: album was trashed, and a folder with a file was added
    DRIVE_NOW = [_item('mein', 'mein', 'ROOT', FOLDER), _item('song', 'song.mp3', 'mein'),
                 _item('new', 'new', 'mein', FOLDER), _item('n1', '1.mp3', 'new'),
                 _item('other', 'other', 'ROOT', FOLDER),
                 _item('elsewhere', 'elsewhere.mp3', 'other'), _item('new2', 'new2.mp3', 'other')]

    def queries(self):
        return [call.kwargs['q'] for call in self.service.files.return_value.list.call_args_list]

    def test_refresh_reads_the_folder_anew_from_drive(self):
        self.drive_has(self.DRIVE_NOW)
        self.assertEqual(self.tree.refresh_from_drive(), '')
        self.assertEqual(self.relpaths(self.tree), ['new/1.mp3', 'song.mp3'])
        self.assertNotIn('album', self.tree)
        self.assertEqual(self.tree._cloud_ids['new/1.mp3'], 'n1')
        # The cache has it, and has the rest as it was
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud/mein')), ['new/1.mp3', 'song.mp3'])
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud/other')), ['elsewhere.mp3'])
        # The folder found by its name, then asked for what the cache keeps of each, and only
        # what's under the folder
        self.assertTrue(self.queries()[0].startswith("name = 'mein' and 'ROOT' in parents"))
        files = self.service.files.return_value
        self.assertIn(clouddirtree.drivecache.FILE_FIELDS, files.list.call_args.kwargs['fields'])
        self.assertTrue(all("'other' in parents" not in query for query in self.queries()))

    def test_refresh_of_a_dir_in_the_tree(self):
        self.drive_has(self.DRIVE_NOW + [_item('album', 'album', 'mein', FOLDER),
                                         _item('t2', 'track2.mp3', 'album')])
        self.assertEqual(self.tree.refresh_from_drive('album'), 'album')
        # Only album was read again
        self.assertEqual(self.relpaths(self.tree), ['album/track2.mp3', 'dup.mp3', 'dup.mp3___DUP__dup2',
                                                   'song.mp3'])
        self.assertTrue(self.queries()[1].startswith("name = 'album' and 'mein' in parents"))

    def test_refresh_of_a_file_or_a_dir_not_in_the_tree_is_of_the_folder_above_it(self):
        self.drive_has(self.DRIVE_NOW + [_item('album', 'album', 'mein', FOLDER)])
        self.assertEqual(self.tree.refresh_from_drive('album/track.mp3'), 'album')
        self.assertEqual(self.tree.refresh_from_drive('album/only/in/the/other'), 'album')
        self.assertEqual(self.tree.refresh_from_drive('nowhere/x.mp3'), '')

    def test_refresh_asks_a_level_of_folders_at_a_time(self):
        self.drive_has([_item('mein', 'mein', 'ROOT', FOLDER)] +
                       [_item('f%d' % (i,), 'f%d' % (i,), 'mein', FOLDER) for i in range(5)] +
                       [_item('x%d' % (i,), 'x.mp3', 'f%d' % (i,)) for i in range(5)])
        with mock.patch('dirdelta.clouddirtree.MAX_FOLDERS_PER_QUERY', 2):
            self.tree.refresh_from_drive()
        # mein by name, what's in it, then f0-f4 two at a time
        self.assertEqual(len(self.queries()), 1 + 1 + 3)
        self.assertEqual(len(self.relpaths(self.tree)), 5)

    def test_a_failed_refresh_leaves_the_tree_and_the_cache_as_they_were(self):
        with open(self.cache) as f:
            cache_before = f.read()
        def listed(query):
            raise _http_error()
        self.listed = listed
        with self.assertRaises(HttpError):
            self.tree.refresh_from_drive()
        self.assertIn('album/track.mp3', self.tree)
        with open(self.cache) as f:
            self.assertEqual(f.read(), cache_before)

    def test_a_refresh_whose_names_cant_be_paths_leaves_the_tree_as_it_was(self):
        self.drive_has([_item('mein', 'mein', 'ROOT', FOLDER), _item('a1', 'a', 'mein', FOLDER),
                        _item('a2', 'a', 'mein', FOLDER)])
        with self.assertRaises(clouddirtree.drivecache.DriveCacheError):
            self.tree.refresh_from_drive()
        self.assertIn('album/track.mp3', self.tree)

    def test_a_folder_drive_no_longer_has_is_an_error(self):
        self.drive_has([_item('other', 'other', 'ROOT', FOLDER)])
        with self.assertRaisesRegex(clouddirtree.drivecache.DriveCacheError, 'no folder /mein'):
            self.tree.refresh_from_drive()

    def test_two_folders_on_the_way_are_an_error(self):
        self.drive_has([_item('mein', 'mein', 'ROOT', FOLDER), _item('mein2', 'mein', 'ROOT', FOLDER)])
        with self.assertRaisesRegex(clouddirtree.drivecache.DriveCacheError, '2 folders named /mein'):
            self.tree.refresh_from_drive()

    def test_quotes_in_a_name_are_escaped(self):
        self.drive_has([_item('q', "it's", 'ROOT', FOLDER), _item('in', 'in.mp3', 'q')])
        clouddirtree.refresh_cache("/it's")
        self.assertTrue(self.queries()[0].startswith("name = 'it\\'s'"))
        self.assertEqual(self.relpaths(clouddirtree.factory("cloud/it's")), ['in.mp3'])

    def test_a_refresh_marks_only_the_folder_fresh(self):
        self.drive_has(self.DRIVE_NOW)
        for path in ('/mein', '/mein/album', '/other'):
            clouddirtree.drivecache.mark_stale(path)
        self.tree.refresh_from_drive()
        self.assertEqual(clouddirtree.drivecache.stale_paths(), ['/other'])

    def test_a_failed_refresh_leaves_the_folder_stale(self):
        clouddirtree.drivecache.mark_stale('/mein')
        self.drive_has([])
        with self.assertRaises(clouddirtree.drivecache.DriveCacheError):
            self.tree.refresh_from_drive()
        self.assertEqual(clouddirtree.drivecache.stale_paths(), ['/mein'])

    def test_with_no_cache_a_refresh_makes_one(self):
        os.remove(self.cache)
        self.drive_has(self.DRIVE_NOW)
        clouddirtree.refresh_cache('/mein')
        with open(self.cache) as f:
            self.assertEqual(json.loads(f.readline()), {clouddirtree.drivecache.ROOT_ID_KEY: 'ROOT'})
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud/mein')), ['new/1.mp3', 'song.mp3'])

    def test_refresh_of_all_of_drive(self):
        self.drive_has(self.DRIVE_NOW)
        clouddirtree.refresh_cache('/')
        self.assertEqual(self.relpaths(clouddirtree.factory('cloud')),
                         ['mein/new/1.mp3', 'mein/song.mp3', 'other/elsewhere.mp3', 'other/new2.mp3'])

    def test_read_progress(self):
        progress = clouddirtree._read_progress
        self.assertEqual(progress(12420, 38455), 'Read 12,420 of about 38,455 files and folders (32%)')
        # Past what was expected, or with nothing expected, it's just the count
        self.assertEqual(progress(40000, 38455), 'Read 40,000 files and folders')
        self.assertEqual(progress(5, None), 'Read 5 files and folders')
        self.assertEqual(progress(5, 0), 'Read 5 files and folders')

    def test_refresh_expects_as_many_as_the_cache_has_there(self):
        self.drive_has(self.DRIVE_NOW)
        with mock.patch('dirdelta.messages.print_progress') as print_progress:
            self.tree.refresh_from_drive()
        # The cache has 5 in mein: song.mp3, album, its track.mp3 and the two dup.mp3
        self.assertEqual(print_progress.call_args_list[0].args[0],
                         'Read 0 of about 5 files and folders (0%)')

if __name__ == '__main__':
    unittest.main()
