import itertools
import json
import os
import re
import shutil
import tempfile
import time
import unittest
from unittest import mock

from dirdelta import clouddirtree
from dirdelta import drivecache
from dirdelta import drivemeta

FOLDER = 'application/vnd.google-apps.folder'


def _item(id, name, parent, mime='audio/mpeg'):
    return {'id': id, 'name': name, 'parents': [parent], 'mimeType': mime}


ITEMS = [_item('mein', 'mein', 'ROOT', FOLDER), _item('song', 'song.mp3', 'mein'),
         _item('album', 'album', 'mein', FOLDER), _item('track', 'track.mp3', 'album'),
         _item('other', 'other', 'ROOT', FOLDER)]


class _Request(object):
    def __init__(self, result):
        self._result = result

    def execute(self, num_retries=0):
        return self._result() if callable(self._result) else self._result


class FakeDrive(object):
    """Drive's files().list (of the queries drivemeta asks), create, update and get_media, in memory"""
    def __init__(self):
        self.files_by_id = {}
        self.contents = {}
        self._ids = itertools.count(1)
        self._times = itertools.count(1)
        self.requests = []

    def files(self):
        return self

    def _modified(self):
        # Later than any time noted before the test (each a second after the one before)
        return drivecache.rfc3339(time.time() + 100 + next(self._times))

    def list(self, q, fields, pageSize=10, pageToken=None):
        self.requests.append(q)
        name, parent = re.match(r"name = '(.*)' and '(.*)' in parents", q).groups()
        found = [md for md in self.files_by_id.values() if md['name'] == name and parent in md['parents']]
        return _Request({'files': found})

    def create(self, body, fields, media_body=None):
        def made():
            md = dict(body, id='new%d' % (next(self._ids),), modifiedTime=self._modified())
            self.files_by_id[md['id']] = md
            if media_body is not None:
                with open(media_body._filename, 'rb') as f:
                    self.contents[md['id']] = f.read()
            return md
        return _Request(made)

    def update(self, fileId, media_body, fields):
        def updated():
            with open(media_body._filename, 'rb') as f:
                self.contents[fileId] = f.read()
            self.files_by_id[fileId]['modifiedTime'] = self._modified()
            return dict(self.files_by_id[fileId])
        return _Request(updated)

    def get_media(self, fileId):
        return _Request(lambda: self.contents[fileId])

    def lines(self, file_id):
        return [json.loads(line) for line in self.contents[file_id].decode().splitlines()]


class DriveMetaTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='dirdelta-drivemeta-')
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.cache = os.path.join(self.tmpdir, 'files.txt')
        with open(self.cache, 'w') as f:
            f.write(json.dumps({drivecache.ROOT_ID_KEY: 'ROOT'}) + '\n')
            for item in ITEMS:
                f.write(json.dumps(item) + '\n')
        for patcher in (mock.patch('dirdelta.drivecache.LINES_FILE', self.cache),
                        mock.patch('dirdelta.driveapi.service', return_value=self.drive)):
            patcher.start()
            self.addCleanup(patcher.stop)

    @property
    def drive(self):
        if not hasattr(self, '_drive'):
            self._drive = FakeDrive()
        return self._drive

    def meta_file(self):
        return next(md for md in self.drive.files_by_id.values() if md['name'] == drivemeta.FILE_NAME)

    def test_the_list_is_uploaded_to_its_meta_dir(self):
        drivemeta.upload('/mein')
        meta = next(md for md in self.drive.files_by_id.values() if md['name'] == 'meta')
        self.assertEqual(meta['parents'], ['mein'])
        lines = self.drive.lines(self.meta_file()['id'])
        self.assertEqual(lines[0], {drivemeta.HEADER_KEY: {'folder': '/mein', 'folderId': 'mein', 'rootId': 'ROOT'}})
        self.assertEqual(sorted(md['id'] for md in lines[1:]), ['album', 'song', 'track'])
        # Again: the same file, without its meta dir in it
        drivemeta.upload('/mein')
        self.assertEqual(len([md for md in self.drive.files_by_id.values() if md['name'] == drivemeta.FILE_NAME]), 1)
        self.assertNotIn(meta['id'], [md['id'] for md in self.drive.lines(self.meta_file()['id'])[1:]])

    def test_uploaded_again_only_once_the_cache_changed(self):
        uploader = drivemeta.Uploader('/mein')
        drivecache.note_updated('/mein')
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self.assertTrue(uploader.upload_if_changed())
            self.assertFalse(uploader.upload_if_changed())
            tree = clouddirtree.factory('cloud/mein')
            # A change in the tree (the cache's line of it) is
            tree._cache_add(_item('new', 'new.mp3', 'mein'))
            self.assertTrue(uploader.is_changed())
            # Not one in its meta dir
            uploader.upload_if_changed()
            tree._cache_add(_item('x', 'x', 'mein'), 'meta/x')
            self.assertFalse(uploader.is_changed())

    def test_one_never_uploaded_is(self):
        with mock.patch('dirdelta.dryrun.DRYRUN', False):
            self.assertTrue(drivemeta.Uploader('/mein').upload_if_changed())

    def test_nothing_is_uploaded_in_a_dry_run(self):
        drivecache.note_updated('/mein')
        with mock.patch('dirdelta.dryrun.DRYRUN', True):
            self.assertFalse(drivemeta.Uploader('/mein').upload_if_changed())
        self.assertEqual(self.drive.files_by_id, {})

    def another_machines_upload(self):
        """Drive's copy, with a file this cache lacks, uploaded by another machine (later than the
        cache's)"""
        drivemeta.upload('/mein')
        file_id = self.meta_file()['id']
        lines = self.drive.lines(file_id) + [_item('theirs', 'theirs.mp3', 'mein')]
        self.drive.contents[file_id] = ''.join(json.dumps(line) + '\n' for line in lines).encode()
        self.drive.files_by_id[file_id]['modifiedTime'] = self.drive._modified()

    def test_a_newer_copy_in_drive_is_used(self):
        drivecache.note_updated('/mein', time.time() - 1000)
        self.another_machines_upload()
        self.assertEqual(drivemeta.check('/mein'), drivemeta.USED)
        tree = clouddirtree.factory('cloud/mein')
        self.assertIn('theirs.mp3', [entry.relpath for entry in tree.iter_files()])
        # Not used again, nor uploaded back: it's this cache's now
        self.assertIsNone(drivemeta.check('/mein'))
        self.assertFalse(drivemeta.Uploader('/mein').is_changed())

    def test_its_own_upload_or_an_older_one_isnt_used(self):
        drivecache.note_updated('/mein')
        drivemeta.upload('/mein')
        self.assertIsNone(drivemeta.check('/mein'))
        self.another_machines_upload()
        # Read from Drive since
        drivecache.note_updated('/mein', time.time() + 10000)
        self.assertIsNone(drivemeta.check('/mein'))

    def test_a_list_of_another_folder_isnt_used(self):
        drivecache.note_updated('/mein', time.time() - 1000)
        self.another_machines_upload()
        file_id = self.meta_file()['id']
        lines = self.drive.lines(file_id)
        lines[0][drivemeta.HEADER_KEY]['folderId'] = 'other'
        self.drive.contents[file_id] = ''.join(json.dumps(line) + '\n' for line in lines).encode()
        self.assertIsNone(drivemeta.check('/mein'))

    def test_none_in_drive(self):
        self.assertIsNone(drivemeta.check('/mein'))
        self.assertEqual(len(self.drive.requests), 1)


if __name__ == '__main__':
    unittest.main()
