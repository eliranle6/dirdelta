import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import clouddirtreefactory
import helpers

REFRESH = 'Refresh cloud/mein from Google Drive'
NO_REFRESH = 'Continue with the cloud files list cache'


class CloudDirTreeFactoryTest(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.mkdtemp(prefix='dirstuff-cloud-factory-')
        self.cache = os.path.join(self.cache_dir, 'sub', 'files.txt')
        for patcher in (mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache),
                        mock.patch('dirdelta.clouddirtree.CloudDirTree')):
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher = mock.patch('dirdelta.clouddirtree.refresh_cache')
        self.addCleanup(patcher.stop)
        self.refresh = patcher.start()

    def tearDown(self):
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def make_cache(self):
        os.makedirs(os.path.dirname(self.cache))
        open(self.cache, 'w').close()

    def test_missing_cache_is_made_without_asking(self):
        with helpers.scripted_option_picker([]):
            clouddirtreefactory.factory_interactive('cloud/mein')
        self.refresh.assert_called_once_with('/mein')

    def test_existing_cache_is_refreshed_only_if_user_asks(self):
        self.make_cache()
        for answer, expected_calls in ((NO_REFRESH, 0), (REFRESH, 1)):
            with helpers.scripted_option_picker([answer]):
                clouddirtreefactory.factory_interactive('cloud/mein')
            self.assertEqual(self.refresh.call_count, expected_calls, answer)

    def test_returns_cloud_tree_for_the_given_path(self):
        tree = clouddirtreefactory.factory_interactive('cloud/mein')
        self.assertIs(tree, clouddirtreefactory.clouddirtree.CloudDirTree.return_value)
        clouddirtreefactory.clouddirtree.CloudDirTree.assert_called_once_with('cloud/mein')

    def header(self):
        with mock.patch('dirdelta.picker.pick_option', return_value=NO_REFRESH) as pick_option:
            clouddirtreefactory.factory_interactive('cloud/mein')
        return pick_option.call_args.kwargs['header']

    def test_the_refresh_prompt_says_if_the_cache_is_stale_in_the_folder(self):
        self.make_cache()
        self.addCleanup(clouddirtreefactory.drivecache.mark_fresh)
        self.assertEqual(self.header(), '')
        # Elsewhere in Drive: not this folder's business
        clouddirtreefactory.drivecache.mark_stale('/other')
        self.assertEqual(self.header(), '')
        for path in ('/mein/album', '/'):
            clouddirtreefactory.drivecache.mark_stale(path)
            self.assertIn('out of date in cloud/mein/album', self.header())
        self.assertIn('cloud/mein/album, cloud', self.header())
        self.assertNotIn('cloud/other', self.header())
