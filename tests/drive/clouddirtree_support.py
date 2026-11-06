"""What a Drive tree's tests share: a cache of cloud/mein (ITEMS), and Drive faked"""
import itertools
import json
import os
import re
import shutil
import tempfile
import unittest
from googleapiclient.errors import HttpError
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from dirdelta.trees import dirtree
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages


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
            f.write(json.dumps({'myDriveRootId': 'ROOT'}) + '\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        # Drive's answer to each create (by what it's made with): a folder made with a generated id
        # keeps it
        created_ids = itertools.count()
        self.create_result = lambda body: {'id': body.get('id', 'new%d' % (next(created_ids),))}
        generated_ids = itertools.count()
        self.service = mock.Mock()
        files = self.service.files.return_value
        files.create.side_effect = lambda body, **_: mock.Mock(
            execute=lambda **_: self.create_result(body))
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
        for patcher in (mock.patch('dirdelta.drive.drivecache.names.LINES_FILE', self.cache),
                        mock.patch('dirdelta.drive.driveapi.service', return_value=self.service),
                        mock.patch('dirdelta.drive.clouddirtree.uploads.MediaFileUpload'),
                        mock.patch('dirdelta.ui.messages.print_line'),
                        mock.patch('dirdelta.util.dryrun.DRYRUN', False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(helpers.remove_drive_cache, self.cache)
        self.addCleanup(drivecache.mark_fresh)
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
        return [call.args[0] for call in messages.print_line.call_args_list]

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

    def move(self, relpath, new_relpath):
        update = self.service.files.return_value.update
        update.return_value.execute.return_value = {
            'id': self.tree._cloud_ids[relpath], 'name': os.path.basename(new_relpath),
            'mimeType': 'audio/mpeg', 'size': '5'}
        return self.tree.move_files([(relpath, new_relpath)])

    def download_to_local_dir(self, relpaths):
        local = localdiskdirtree.LocalDiskDirTree(self.local_dir, silent=True)
        files = [self.tree.get_node(relpath).data for relpath in relpaths]
        local.copy_inner_entries_from_dirtree(dirtree.DirTree.from_file_entries(files, '/mein'),
                                              self.tree)
        return local

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


if __name__ == '__main__':
    unittest.main()
