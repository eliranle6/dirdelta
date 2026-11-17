"""Moving an import's files into the replica (phoneimport/applying.py), and the import through the web
version's API (web/importing.py)"""
import os
import unittest
from unittest import mock

from dirdelta.hashes import hashcache
from dirdelta.known import replicas
from dirdelta.phoneimport import applying, copying, store
from dirdelta.web import importing
from import_support import ImportTest


class ApplyingTest(ImportTest):
    def copied(self, files):
        for relpath, contents in files.items():
            self.write(self.source, relpath, contents)
        found = store.create(self.source, self.dest)
        self.wait_for(copying.copy(found).thread)
        return found

    def test_a_dry_run_moves_nothing(self):
        found = self.copied({'DCIM/a.jpg': 'a'})
        found.files['DCIM/a.jpg']['target'] = 'media/Trip'
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.wait_for(applying.apply(found).thread)
        self.assertFalse(os.path.exists(os.path.join(self.dest, 'media/Trip/a.jpg')))
        self.assertEqual(store.COPIED, found.files['DCIM/a.jpg']['state'])
        self.assertIn("Would move DCIM/a.jpg → media/Trip/a.jpg", [line for line, _ in applying.applying_of(found.id).lines])

    def test_files_go_into_their_dirs_never_over_another_file(self):
        found = self.copied({'DCIM/a.jpg': 'a', 'DCIM/b.jpg': 'new b', 'DCIM/c.jpg': 'not chosen'})
        self.write(self.dest, 'media/Trip/b.jpg', 'another b')
        found.files['DCIM/a.jpg']['target'] = found.files['DCIM/b.jpg']['target'] = 'media/Trip'
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.wait_for(applying.apply(found).thread)
        with open(os.path.join(self.dest, 'media/Trip/b.jpg')) as kept, open(os.path.join(self.dest, 'media/Trip/b (2).jpg')) as moved:
            self.assertEqual(('another b', 'new b'), (kept.read(), moved.read()))
        self.assertEqual(found.files['DCIM/a.jpg']['sha1'], hashcache.get(os.path.join(self.dest, 'media/Trip/a.jpg'), 'sha1'))
        self.assertEqual({'DCIM/a.jpg': store.MOVED, 'DCIM/b.jpg': store.MOVED, 'DCIM/c.jpg': store.COPIED},
                         {relpath: info['state'] for relpath, info in store.load(found.id).files.items()})

    def test_the_same_file_there_already_isnt_moved_again(self):
        found = self.copied({'DCIM/a.jpg': 'a'})
        self.write(self.dest, 'media/Trip/a.jpg', 'a')
        found.files['DCIM/a.jpg']['target'] = 'media/Trip'
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.wait_for(applying.apply(found).thread)
        self.assertEqual(['a.jpg'], os.listdir(os.path.join(self.dest, 'media/Trip')))
        self.assertFalse(os.path.exists(found.local_path('DCIM/a.jpg')))
        self.assertEqual(store.MOVED, found.files['DCIM/a.jpg']['state'])


class ImportPageTest(ImportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('dirdelta.known.replicas.load', return_value=replicas.Replicas(sorts=[('cloud/x', self.dest)]))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.routes = importing.routes()

    def call(self, method, path, query=None, body=None):
        return self.routes[(method, path)](query or {}, body or {})

    def test_an_import_by_day_with_what_the_replica_has_then_chosen_and_moved(self):
        self.write(self.dest, 'media/Trip/PXL_20260224_1.jpg', 'old one')
        self.write(self.source, 'DCIM/PXL_20260224_1.jpg', 'old one')
        self.write(self.source, 'DCIM/PXL_20260225_2.jpg', 'new one')
        self.assertEqual(self.dest, self.call('GET', '/api/imports')['defaultDest'])
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: self.call('GET', '/api/import', {'id': import_id})['indexed'] and
                        copying.copying_of(import_id).phase == 'done')
        state = self.call('GET', '/api/import', {'id': import_id})
        self.assertEqual(['2026-02-24', '2026-02-25'], [day['day'] for day in state['days']])
        first, second = state['days'][0]['files'][0], state['days'][1]['files'][0]
        self.assertEqual([{'replica': self.dest, 'relpath': 'media/Trip/PXL_20260224_1.jpg', 'how': 'same name and size'}],
                         first['have'])
        self.assertEqual([], second['have'])
        self.assertEqual(['media/Trip'], state['days'][1]['suggested'])
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': [first['rel']], 'skip': True})
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': [second['rel']], 'target': 'media/Trip'})
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            self.call('POST', '/api/import/apply', body={'id': import_id})
            self.wait_for(applying.applying_of(import_id).thread)
        self.assertTrue(os.path.exists(os.path.join(self.dest, 'media/Trip/PXL_20260225_2.jpg')))
        self.assertEqual({'pending': 0, 'copied': 0, 'moved': 1, 'skipped': 1},
                         self.call('GET', '/api/import', {'id': import_id})['counts'])

    def test_a_dir_outside_the_replica_cant_be_chosen(self):
        self.write(self.source, 'DCIM/a.jpg', 'a')
        import_id = self.call('POST', '/api/imports/new', body={'source': self.source, 'dest': self.dest})['id']
        self.wait_until(lambda: copying.copying_of(import_id).phase == 'done')
        self.call('POST', '/api/import/assign', body={'id': import_id, 'rels': ['DCIM/a.jpg'], 'target': '../../etc'})
        self.assertIsNone(store.load(import_id).files['DCIM/a.jpg']['target'])


if __name__ == '__main__':
    unittest.main()
