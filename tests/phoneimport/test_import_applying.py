"""Moving an import's files into the replica (phoneimport/applying.py), and the import through the web
version's API (web/importing/)"""
import os
import unittest
from unittest import mock

from dirdelta.hashes import hashcache
from dirdelta.known import replicas
from dirdelta.phoneimport import applying, copying, store
from dirdelta.web import importing
from import_support import ImportTest


class ApplyingTest(ImportTest):
    def listed(self, files, copied=True):
        for relpath, contents in files.items():
            self.write(self.source, relpath, contents)
        found = store.create(self.source, self.dest)
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
        self.assertIn("Would move Camera/a.jpg → media/Trip/a.jpg", [line for line, _ in applying.applying_of(found.id).lines])

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
        self.assertEqual(self.dest, self.call('GET', '/api/imports')['defaultDest'])
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        state = self.call('GET', '/api/import', {'id': import_id})
        self.assertEqual(['2026-02-24', '2026-02-25'], [day['day'] for day in state['days']])
        first, second = state['days'][0]['files'][0], state['days'][1]['files'][0]
        self.assertEqual([{'replica': self.dest, 'relpath': 'media/Trip/PXL_20260224_1.jpg', 'how': 'namePhoneUnhashed'}],
                         first['have'])
        self.assertEqual([], second['have'])
        self.assertEqual(['media/Trip'], state['days'][1]['suggested'])
        self.assertEqual({'files': 1, 'size': 7}, state['overview']['nameOnly'])
        self.call('POST', '/api/import/read', body={'id': import_id, 'which': 'nameOnly'})
        self.wait_until(lambda: self.done(import_id))
        brief = self.call('GET', '/api/import', {'id': import_id, 'files': '0'})
        self.assertNotIn('days', brief)
        self.assertEqual((2, 1, 1, 1), (brief['overview']['total'], brief['overview']['hashed'],
                                        brief['overview']['replicas'][0]['nameReplicaUnhashed'], brief['overview']['inNone']))
        self.assertEqual(1, brief['replicas'][0]['unhashed'])
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': [first['rel']], 'skip': True})
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': [second['rel']], 'target': 'media/Trip'})
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.call('POST', '/api/import/apply', body={'id': import_id})
            self.wait_for(applying.applying_of(import_id).thread)
        self.assertTrue(os.path.exists(os.path.join(self.dest, 'media/Trip/PXL_20260225_2.jpg')))
        self.assertEqual({'pending': 0, 'copied': 0, 'moved': 1, 'skipped': 1},
                         self.call('GET', '/api/import', {'id': import_id})['counts'])
        self.assertTrue(self.call('POST', '/api/import/end', body={'id': import_id})['ok'])
        self.assertEqual([], self.call('GET', '/api/imports')['imports'])

    def test_starting_the_same_source_into_the_same_replica_again_opens_its_import_listed_again(self):
        self.write(self.source, 'a.jpg', 'a')
        body = {'source': self.source, 'dest': self.dest}
        import_id = self.call('POST', '/api/imports/new', body=body)['id']
        self.wait_until(lambda: self.done(import_id))
        self.write(self.source, 'b.jpg', 'b')
        self.assertEqual(import_id, self.call('POST', '/api/imports/new', body=body)['id'])
        self.wait_until(lambda: self.done(import_id))
        self.assertEqual({'a.jpg', 'b.jpg'}, set(store.load(import_id).files()))

    def test_a_dir_outside_the_replica_cant_be_chosen(self):
        self.write(self.source, 'a.jpg', 'a')
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.done(import_id))
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': ['a.jpg'], 'target': '../../etc'})
        self.assertIsNone(store.load(import_id).files()['a.jpg']['target'])


if __name__ == '__main__':
    unittest.main()
