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

    def test_a_pair_added_is_a_favorite_and_one_inside_the_other_isnt_a_pair(self):
        add = self.routes[('POST', '/api/pairs/add')]
        self.assertFalse(add({}, {'a': self.root, 'b': os.path.join(self.root, 'photos')})['ok'])
        self.assertFalse(add({}, {'a': os.path.join(self.root, 'photos'), 'b': 'cloud'})['ok'])
        self.assertTrue(add({}, {'a': os.path.join(self.root, 'photos'), 'b': 'cloud/photos/'})['ok'])
        add({}, {'a': os.path.join(self.root, 'photos'), 'b': 'cloud/photos'})
        self.assertEqual([(os.path.join(self.root, 'photos'), 'cloud/photos')], replicas.load().favorites)


if __name__ == '__main__':
    unittest.main()
