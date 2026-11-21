"""Moving an import's files into the replica (phoneimport/applying.py), and the import through the web
version's API (web/importing/)"""
import hashlib
import os
import unittest
from unittest import mock

from dirdelta.hashes import hashcache
from dirdelta.known import replicas
from dirdelta.phoneimport import applying, copying, removing, store
from dirdelta.web import importing
from dirdelta.web.importing import checks as checking
from dirdelta.web.importing.state import summary
from import_support import ImportTest


class ApplyingTest(ImportTest):
    def listed(self, files, copied=True):
        for relpath, contents in files.items():
            self.write(self.source, relpath, contents)
        found = store.create(self.source, self.dest, 'disk-1')
        self.wait_for(copying.read(self.source, relpaths=list(files) if copied else []).thread)
        return found

    def states(self, found):
        return {relpath: info['state'] for relpath, info in found.files().items()}

    def apply(self, found, is_dry_run=False):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', is_dry_run):
            self.wait_for(applying.apply(found).thread)

    def test_a_dry_run_moves_nothing(self):
        found = self.listed({'Camera/a.jpg': 'a'})
        found.choose(['Camera/a.jpg'], 'media/Trip')
        self.apply(found, is_dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.dest, 'media/Trip/a.jpg')))
        self.assertEqual({'Camera/a.jpg': store.COPIED}, self.states(found))
        # (A phone's or a folder's files are copied: it keeps its own)
        self.assertIn("Would copy Camera/a.jpg → media/Trip/a.jpg", [line for line, _ in applying.applying_of(found.id).lines])

    def test_files_go_into_their_dirs_never_over_another_file(self):
        found = self.listed({'Camera/a.jpg': 'a', 'Camera/b.jpg': 'new b', 'Camera/c.jpg': 'not chosen'})
        self.write(self.dest, 'media/Trip/b.jpg', 'another b')
        found.choose(['Camera/a.jpg', 'Camera/b.jpg'], 'media/Trip')
        self.apply(found)
        with open(os.path.join(self.dest, 'media/Trip/b.jpg')) as kept, open(os.path.join(self.dest, 'media/Trip/b (2).jpg')) as moved:
            self.assertEqual(('another b', 'new b'), (kept.read(), moved.read()))
        self.assertEqual(found.files()['Camera/a.jpg']['sha1'], hashcache.get(os.path.join(self.dest, 'media/Trip/a.jpg'), 'sha1'))
        store._loaded.clear()
        self.assertEqual({'Camera/a.jpg': store.MOVED, 'Camera/b.jpg': store.MOVED, 'Camera/c.jpg': store.COPIED},
                         self.states(store.load(found.id)))

    def test_a_file_still_on_the_phone_is_copied_as_its_moved(self):
        found = self.listed({'Camera/a.jpg': 'a'}, copied=False)
        found.choose(['Camera/a.jpg'], 'media/Trip')
        self.apply(found)
        with open(os.path.join(self.dest, 'media/Trip/a.jpg')) as moved:
            self.assertEqual('a', moved.read())
        self.assertTrue(found.files()['Camera/a.jpg']['sha1'])
        self.assertEqual({'Camera/a.jpg': store.MOVED}, self.states(found))

    def test_the_same_file_there_already_isnt_moved_again(self):
        found = self.listed({'Camera/a.jpg': 'a'})
        self.write(self.dest, 'media/Trip/a.jpg', 'a')
        found.choose(['Camera/a.jpg'], 'media/Trip')
        self.apply(found)
        self.assertEqual(['a.jpg'], os.listdir(os.path.join(self.dest, 'media/Trip')))
        self.assertFalse(os.path.exists(found.pool.local_path('Camera/a.jpg')))
        self.assertEqual({'Camera/a.jpg': store.MOVED}, self.states(found))


class FakeDriveTree(object):
    """A Drive folder's tree: its files' contents, downloaded, trashed, or moved into another"""

    def __init__(self, files):
        self.files, self.trashed, self.moved = dict(files), [], []

    def fullpath(self):
        return '/unsorted'

    def get_node(self, relpath):
        return None

    def fetch_file(self, relpath, local_path):
        with open(local_path, 'w') as fetched:
            fetched.write(self.files[relpath])

    def remove_files(self, file_entries):
        self.trashed.extend(entry.relpath for entry in file_entries)

    def has_file(self, relpath):
        return relpath in self.files

    def known_hash(self, relpath, algorithm):
        return hashlib.sha1(self.files[relpath].encode()).hexdigest() if relpath in self.files else None

    def move_files(self, moves, to=None):
        self.moved.extend(moves)
        return moves


class DriveApplyingTest(ImportTest):
    def drive_import(self, dest, files):
        found = store.create('cloud/unsorted', dest, 'disk-1')
        found.pool.add({relpath: (len(text), 1, hashlib.sha1(text.encode()).hexdigest()) for relpath, text in files.items()})
        return found

    def test_a_drive_file_is_downloaded_into_its_dir_then_moved_to_drives_trash(self):
        found = self.drive_import(self.dest, {'a.jpg': 'a', 'b.jpg': 'b'})
        tree = FakeDriveTree({'a.jpg': 'a', 'b.jpg': 'b'})
        found.choose(['a.jpg'], 'media/Trip')
        with mock.patch.object(type(found.pool), 'tree', lambda pool: tree), mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.wait_for(applying.apply(found).thread)
        with open(os.path.join(self.dest, 'media/Trip/a.jpg')) as moved:
            self.assertEqual('a', moved.read())
        self.assertEqual(['a.jpg'], tree.trashed)
        self.assertEqual({'a.jpg': store.MOVED, 'b.jpg': store.PENDING}, {relpath: info['state'] for relpath, info in found.files().items()})

    def test_into_a_drive_replica_its_moved_in_drive_and_one_there_already_trashed(self):
        found = self.drive_import('cloud/photos', {'a.jpg': 'a', 'b.jpg': 'b'})
        source, dest = FakeDriveTree({'a.jpg': 'a', 'b.jpg': 'b'}), FakeDriveTree({'Trip/b.jpg': 'b'})
        found.choose(['a.jpg', 'b.jpg'], 'Trip')
        with mock.patch.object(type(found.pool), 'tree', lambda pool: source), \
                mock.patch('dirdelta.drive.clouddirtree.tree.factory', return_value=dest), mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.wait_for(applying.apply(found).thread)
        self.assertEqual([('a.jpg', 'Trip/a.jpg')], source.moved)
        self.assertEqual(['b.jpg'], source.trashed)


class ImportPageTest(ImportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('dirdelta.known.replicas.load', return_value=replicas.Replicas(sorts=[('cloud/x', self.dest)]))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.routes = importing.routes()

    def call(self, method, path, query=None, body=None):
        return self.routes[(method, path)](query or {}, body or {})

    def done(self, import_id):
        state = self.call('GET', '/api/import', {'id': import_id})
        return state['indexed'] and not state['checking']['busy'] and state['reading']['phase'] == 'done'

    def test_an_import_compared_by_name_and_size_then_hashed_on_asking_then_chosen_and_moved(self):
        self.write(self.dest, 'media/Trip/PXL_20260224_1.jpg', 'old one')
        self.write(self.source, 'PXL_20260224_1.jpg', 'old one')
        self.write(self.source, 'PXL_20260225_2.jpg', 'new one')
        inbox = next(found for found in self.call('GET', '/api/imports')['inboxes'] if found['path'] == 'cloud/x')
        self.assertEqual(('drive', self.dest), (inbox['kind'], inbox['dests'][0]['path']))
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        state = self.call('GET', '/api/import', {'id': import_id})
        # (A folder's files are one group; a phone's by where they are on it: test_import_copying)
        self.assertEqual(['all'], [group['key'] for group in state['groups']])
        days = state['groups'][0]['days']
        self.assertEqual(['2026-02-24', '2026-02-25'], [day['day'] for day in days])
        first, second = days[0]['files'][0], days[1]['files'][0]
        self.assertEqual([{'replica': self.dest, 'relpath': 'media/Trip/PXL_20260224_1.jpg', 'how': 'namePhoneUnhashed'}],
                         first['have'])
        self.assertEqual([], second['have'])
        self.assertEqual(['media/Trip'], days[1]['suggested'])
        self.assertEqual({'files': 1, 'size': 7}, state['overview']['nameOnly'])
        self.call('POST', '/api/import/read', body={'id': import_id, 'which': 'nameOnly'})
        self.wait_until(lambda: self.done(import_id))
        brief = self.call('GET', '/api/import', {'id': import_id, 'files': '0'})
        self.assertNotIn('groups', brief)
        # (Only the one asked for is copied, and hashed: nothing is copied on its own)
        self.assertEqual((2, 1, 1, 1), (brief['overview']['total'], brief['overview']['hashed'],
                                        brief['overview']['replicas'][0]['nameReplicaUnhashed'], brief['overview']['inNone']))
        self.assertEqual(1, brief['replicas'][0]['unhashed'])
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': [first['rel']], 'skip': True})
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': [second['rel']], 'target': 'media/Trip'})
        # (Offered first next time, kept with the replica's recent dirs)
        self.assertEqual(['media/Trip'], self.call('GET', '/api/import', {'id': import_id})['recentDirs'])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.call('POST', '/api/import/apply', body={'id': import_id})
            self.wait_for(applying.applying_of(import_id).thread)
        self.assertTrue(os.path.exists(os.path.join(self.dest, 'media/Trip/PXL_20260225_2.jpg')))
        self.assertEqual({'pending': 0, 'copied': 0, 'moved': 1, 'skipped': 1},
                         self.call('GET', '/api/import', {'id': import_id})['counts'])
        self.assertTrue(self.call('POST', '/api/import/end', body={'id': import_id})['ok'])
        self.assertEqual([], [found for inbox in self.call('GET', '/api/imports')['inboxes'] for found in inbox['imports']])

    def test_the_files_a_replica_has_already_are_kept_and_count_as_not_left_to_sort(self):
        self.write(self.dest, 'media/a.jpg', 'a')
        self.write(self.source, 'a.jpg', 'a')
        self.write(self.source, 'b.jpg', 'bb')
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        listed = [found for inbox in self.call('GET', '/api/imports')['inboxes'] for found in inbox['imports']]
        self.assertEqual((0, 1), (listed[0]['already']['contents'], listed[0]['already']['name']))
        # (Kept: as after a restart, with the phone unplugged)
        with store._lock:
            store._loaded.clear()
        self.assertEqual((0, 1), (summary(store.load(import_id))['already']['contents'], summary(store.load(import_id))['already']['name']))

    def test_starting_the_same_source_into_the_same_replica_again_opens_its_import_listed_again(self):
        self.write(self.source, 'a.jpg', 'a')
        body = {'source': self.source, 'dest': self.dest}
        import_id = self.call('POST', '/api/imports/new', body=body)['id']
        self.wait_until(lambda: self.done(import_id))
        self.write(self.source, 'b.jpg', 'b')
        self.assertEqual(import_id, self.call('POST', '/api/imports/new', body=body)['id'])
        self.wait_until(lambda: self.done(import_id))
        self.assertEqual({'a.jpg', 'b.jpg'}, set(store.load(import_id).files()))

    def test_another_disk_at_the_replicas_path_is_another_replica(self):
        self.write(self.source, 'a.jpg', 'a')
        body = {'source': self.source, 'dest': self.dest}
        with mock.patch('dirdelta.known.replicanames.identity', return_value='uuid:ONE:/'):
            import_id = self.call('POST', '/api/imports/new', body=body)['id']
            self.wait_until(lambda: self.done(import_id))
        checking._identities.clear()
        with mock.patch('dirdelta.known.replicanames.identity', return_value='uuid:TWO:/'):
            self.assertTrue(self.call('GET', '/api/import', {'id': import_id, 'files': '0'})['otherDisk'])
            self.assertFalse(self.call('POST', '/api/import/apply', body={'id': import_id})['ok'])
            self.assertNotEqual(import_id, self.call('POST', '/api/imports/new', body=body)['id'])

    def test_a_file_the_replica_has_is_removed_from_the_source_one_it_lacks_never(self):
        self.write(self.dest, 'media/Trip/PXL_20260224_1.jpg', 'old one')
        self.write(self.source, 'PXL_20260224_1.jpg', 'old one')
        self.write(self.source, 'PXL_20260225_2.jpg', 'new one')
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        self.call('GET', '/api/import', {'id': import_id})
        self.wait_until(lambda: self.done(import_id))
        refused = self.call('POST', '/api/import/remove', body={'id': import_id, 'rels': ['PXL_20260224_1.jpg', 'PXL_20260225_2.jpg']})
        self.assertFalse(refused['ok'])
        self.assertEqual(2, len(os.listdir(self.source)))
        # (A dry run removes nothing)
        self.assertTrue(self.call('POST', '/api/import/remove', body={'id': import_id, 'rels': ['PXL_20260224_1.jpg']})['ok'])
        self.wait_for(removing.removing_of(import_id).thread)
        self.assertEqual(2, len(os.listdir(self.source)))
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.call('POST', '/api/import/remove', body={'id': import_id, 'rels': ['PXL_20260224_1.jpg']})
            self.wait_for(removing.removing_of(import_id).thread)
        self.assertEqual(['PXL_20260225_2.jpg'], os.listdir(self.source))
        rels = [file['rel'] for group in self.call('GET', '/api/import', {'id': import_id})['groups'] for day in group['days'] for file in day['files']]
        self.assertEqual(['PXL_20260225_2.jpg'], rels)

    def test_the_files_without_a_date_come_after_the_days(self):
        self.write(self.source, 'IMG_20250101_1.jpg', 'a')
        os.utime(self.write(self.source, 'x.jpg', 'b'), (0, 0))
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        days = self.call('GET', '/api/import', {'id': import_id})['groups'][0]['days']
        self.assertEqual('2025-01-01', days[0]['day'])
        self.assertEqual(2, len(days))

    def test_a_dir_outside_the_replica_cant_be_chosen(self):
        self.write(self.source, 'a.jpg', 'a')
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': ['a.jpg'], 'target': '../../etc'})
        self.assertIsNone(store.load(import_id).files()['a.jpg']['target'])


if __name__ == '__main__':
    unittest.main()
