import unittest

from dirdelta import paths


class PathsTest(unittest.TestCase):
    def test_components_ignore_empty_parts(self):
        self.assertEqual(paths.components('/cloud//mein/'), ['cloud', 'mein'])

    def test_join_cloud(self):
        self.assertEqual(paths.join_cloud('me/music'), 'cloud/me/music')
        self.assertEqual(paths.join_cloud(''), 'cloud')

    def test_cloud_paths_start_with_cloud(self):
        self.assertTrue(paths.is_cloud_path('cloud/mein'))
        self.assertTrue(paths.is_cloud_path('/cloud/mein'))
        self.assertTrue(paths.is_cloud_path('cloud'))
        self.assertFalse(paths.is_cloud_path('/home/cloud/mein'))
        self.assertFalse(paths.is_cloud_path('clouds/mein'))

    def test_path_in_cloud(self):
        self.assertEqual(paths.path_in_cloud('cloud/mein/music'), '/mein/music')
        self.assertEqual(paths.path_in_cloud('cloud'), '/')



class IsAtOrUnderTest(unittest.TestCase):
    def test_relpaths_and_absolute_paths_the_root_having_all(self):
        self.assertTrue(paths.is_at_or_under('a/b', 'a'))
        self.assertTrue(paths.is_at_or_under('a', 'a'))
        self.assertFalse(paths.is_at_or_under('ab', 'a'))
        self.assertTrue(paths.is_at_or_under('a/b', ''))
        self.assertTrue(paths.is_at_or_under('/x/y', '/x/'))
        self.assertTrue(paths.is_at_or_under('/x', '/'))
        self.assertFalse(paths.is_at_or_under('/xy', '/x'))


if __name__ == '__main__':
    unittest.main()
