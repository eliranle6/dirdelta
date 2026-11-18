"""Adding a replica pair from the web version (web/adding.py)"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real caches and config aren't touched)
from dirdelta.known import replicas
from dirdelta.web import adding


class AddingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        patcher = mock.patch('dirdelta.known.replicas.REPLICAS_FILE', os.path.join(self.temp, 'replicas.json'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = os.path.realpath(os.path.join(self.temp, 'disk'))
        for relpath in ('photos/2026', 'backup', '.hidden'):
            os.makedirs(os.path.join(self.root, relpath))
        self.routes = adding.routes()

    def test_a_local_folder_is_browsed_by_its_folders_not_hidden_ones(self):
        found = self.routes[('GET', '/api/browse')]({'path': self.root}, {})
        self.assertEqual((['backup', 'photos'], os.path.dirname(self.root)), (found['dirs'], found['parent']))
        self.assertIn('error', self.routes[('GET', '/api/browse')]({'path': os.path.join(self.root, 'nothing')}, {}))

    def test_a_folder_is_added_as_a_replica_or_an_inbox_not_in_another_and_forgotten(self):
        add, forget = self.routes[('POST', '/api/add')], self.routes[('POST', '/api/forget')]
        photos = os.path.join(self.root, 'photos')
        self.assertTrue(add({}, {'path': photos})['ok'])
        self.assertTrue(add({}, {'path': 'cloud/photos/'})['ok'])
        self.assertFalse(add({}, {'path': os.path.join(photos, '2026'), 'as': 'inbox'})['ok'])
        self.assertFalse(add({}, {'path': self.root, 'as': 'inbox'})['ok'])
        self.assertFalse(add({}, {'path': 'cloud'})['ok'])
        self.assertTrue(add({}, {'path': os.path.join(self.root, 'backup'), 'as': 'inbox'})['ok'])
        known = replicas.load()
        self.assertEqual(([photos, 'cloud/photos'], [os.path.join(self.root, 'backup')], [(photos, 'cloud/photos')]),
                         (known.replica_paths(), known.inbox_paths(), known.pairs()))
        forget({}, {'path': photos})
        self.assertEqual(['cloud/photos'], replicas.load().replica_paths())


if __name__ == '__main__':
    unittest.main()
