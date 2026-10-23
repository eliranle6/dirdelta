import json
import os
import tempfile
import unittest
from unittest import mock

from dirdelta import clouddirtree

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
        patcher = mock.patch('dirdelta.clouddirtree.FILE_LIST_CACHE', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.remove, self.cache)

    def _relpaths(self, tree):
        return sorted(entry.relpath for entry in tree.iter_files())

    def test_builds_files_under_the_requested_folder_only(self):
        tree = clouddirtree.CloudDirTree('cloud/mein')
        self.assertIn('/song.mp3', self._relpaths(tree))
        self.assertIn('/album/track.mp3', self._relpaths(tree))
        self.assertNotIn('/elsewhere.mp3', self._relpaths(tree))

    def test_folders_become_dirs_and_files_become_files(self):
        tree = clouddirtree.CloudDirTree('cloud/mein')
        self.assertIsNotNone(tree.get_node('/album'))
        self.assertNotIn('/album', self._relpaths(tree))

    def test_same_named_files_both_kept_with_dup_suffix(self):
        tree = clouddirtree.CloudDirTree('cloud/mein')
        dups = [path for path in self._relpaths(tree) if path.startswith('/dup.mp3')]
        self.assertEqual(len(dups), 2)
        self.assertIn('/dup.mp3', dups)

    def test_fullpath_is_the_path_inside_the_drive(self):
        tree = clouddirtree.CloudDirTree('cloud/mein')
        self.assertEqual(tree.get_node('/album/track.mp3').data.fullpath, '/mein/album/track.mp3')

    def test_path_components_ignores_empty_parts(self):
        self.assertEqual(clouddirtree.CloudDirTree.path_components('/cloud//mein/'), ['cloud', 'mein'])


if __name__ == '__main__':
    unittest.main()
