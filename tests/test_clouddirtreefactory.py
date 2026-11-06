import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from dirdelta.drive import clouddirtreefactory
import helpers

REFRESH = clouddirtreefactory.OPTION_REFRESH
NO_REFRESH = clouddirtreefactory.OPTION_NO_REFRESH


class CloudDirTreeFactoryTest(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.mkdtemp(prefix='dirstuff-cloud-factory-')
        self.cache = os.path.join(self.cache_dir, 'sub', 'files.txt')
        for patcher in (mock.patch('dirdelta.drive.drivecache.LINES_FILE', self.cache),
                        mock.patch('dirdelta.drive.clouddirtree.tree.CloudDirTree')):
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher = mock.patch('dirdelta.drive.clouddirtree.refresh_cache')
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

    def test_nothing_is_the_first_option_and_goes_back(self):
        self.make_cache()
        for answer in (clouddirtreefactory.OPTION_NOTHING, None):
            with mock.patch('dirdelta.ui.picker.pick_option', return_value=answer) as pick_option:
                self.assertIsNone(clouddirtreefactory.factory_interactive('cloud/mein'))
            self.assertEqual(pick_option.call_args.args[0], [clouddirtreefactory.OPTION_NOTHING, NO_REFRESH, REFRESH])
        self.refresh.assert_not_called()
        clouddirtreefactory.clouddirtree.tree.CloudDirTree.assert_not_called()

    def header(self):
        with mock.patch('dirdelta.ui.picker.pick_option', return_value=NO_REFRESH) as pick_option:
            clouddirtreefactory.factory_interactive('cloud/mein')
        return pick_option.call_args.kwargs['header']

    def test_the_refresh_prompt_is_brief_and_says_how_old_the_list_is(self):
        self.make_cache()
        when = time.mktime((2026, 10, 26, 9, 33, 0, 0, 0, -1))
        clouddirtreefactory.drivecache.note_updated('/mein', when)
        self.assertEqual(self.header().splitlines()[:3], [
            "Refresh cloud/mein from Google Drive?", "",
            "Its file list is from 2026-10-26 09:33. Refreshing shows changes made elsewhere, but takes a while."])

    def test_the_refresh_prompt_says_if_the_cache_is_stale_in_the_folder(self):
        self.make_cache()
        self.addCleanup(clouddirtreefactory.drivecache.mark_fresh)
        self.assertNotIn('out of date', self.header())
        # Elsewhere in Drive: not this folder's business
        clouddirtreefactory.drivecache.mark_stale('/other')
        self.assertNotIn('out of date', self.header())
        for path in ('/mein/album', '/'):
            clouddirtreefactory.drivecache.mark_stale(path)
            self.assertIn('out of date in cloud/mein/album', self.header())
        self.assertIn('cloud/mein/album, cloud', self.header())
        self.assertNotIn('cloud/other', self.header())
