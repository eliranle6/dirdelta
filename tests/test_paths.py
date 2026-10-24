import unittest

from dirdelta import paths


class PathsTest(unittest.TestCase):
    def test_components_ignore_empty_parts(self):
        self.assertEqual(paths.components('/cloud//mein/'), ['cloud', 'mein'])

    def test_cloud_paths_start_with_cloud(self):
        self.assertTrue(paths.is_cloud_path('cloud/mein'))
        self.assertTrue(paths.is_cloud_path('/cloud/mein'))
        self.assertTrue(paths.is_cloud_path('cloud'))
        self.assertFalse(paths.is_cloud_path('/home/cloud/mein'))
        self.assertFalse(paths.is_cloud_path('clouds/mein'))

    def test_path_in_cloud(self):
        self.assertEqual(paths.path_in_cloud('cloud/mein/music'), '/mein/music')
        self.assertEqual(paths.path_in_cloud('cloud'), '/')


if __name__ == '__main__':
    unittest.main()
