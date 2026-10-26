import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import clouddirtreefactory
import helpers


def _fake_drive_service(pages):
    """A Drive service whose files().list(...).execute() returns the given pages in order."""
    service = mock.Mock()
    service.files.return_value.get.return_value.execute.return_value = {'id': 'ROOT'}
    service.files.return_value.list.return_value.execute.side_effect = pages
    return service


class CloudDirTreeFactoryTest(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.mkdtemp(prefix='dirstuff-cloud-factory-')
        self.cache = os.path.join(self.cache_dir, 'sub', 'files.txt')
        for patcher in (mock.patch('dirdelta.drivecache.FILE_LIST_CACHE', self.cache),
                        mock.patch('dirdelta.clouddirtree.CloudDirTree')):
            self.addCleanup(patcher.stop)
            patcher.start()

    def tearDown(self):
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def test_missing_cache_is_created_without_asking(self):
        with mock.patch('dirdelta.clouddirtreefactory._refresh_cache') as refresh, helpers.scripted_option_picker([]):
            clouddirtreefactory.factory_interactive('cloud/mein')
        refresh.assert_called_once_with()
        self.assertTrue(os.path.isdir(os.path.dirname(self.cache)))

    def test_existing_cache_is_refreshed_only_if_user_asks(self):
        os.makedirs(os.path.dirname(self.cache))
        open(self.cache, 'w').close()
        for answer, expected_calls in (('Continue with old cloud files list cache', 0),
                                       ('Refresh cloud files list cache', 1)):
            with mock.patch('dirdelta.clouddirtreefactory._refresh_cache') as refresh, \
                 helpers.scripted_option_picker([answer]):
                clouddirtreefactory.factory_interactive('cloud/mein')
            self.assertEqual(refresh.call_count, expected_calls, answer)

    def test_returns_cloud_tree_for_the_given_path(self):
        with mock.patch('dirdelta.clouddirtreefactory._refresh_cache'):
            tree = clouddirtreefactory.factory_interactive('cloud/mein')
        self.assertIs(tree, clouddirtreefactory.clouddirtree.CloudDirTree.return_value)
        clouddirtreefactory.clouddirtree.CloudDirTree.assert_called_once_with('cloud/mein')

    def test_scan_writes_one_json_line_per_file_across_pages(self):
        pages = [{'files': [{'id': 'a'}, {'id': 'b'}], 'nextPageToken': 'p2'}, {'files': [{'id': 'c'}]}]
        out = io.StringIO()
        with mock.patch('dirdelta.driveapi.service', return_value=_fake_drive_service(pages)), \
             mock.patch('dirdelta.messages.print_line'), mock.patch('dirdelta.messages.print_progress'):
            clouddirtreefactory._scan_drive_files_list(out)
        root_line, *file_lines = out.getvalue().splitlines()
        self.assertEqual(json.loads(root_line), {'myDriveRootId': 'ROOT'})
        self.assertEqual([json.loads(line)['id'] for line in file_lines], ['a', 'b', 'c'])

    def test_scan_skips_the_trash(self):
        service = _fake_drive_service([{'files': []}])
        with mock.patch('dirdelta.driveapi.service', return_value=service), \
             mock.patch('dirdelta.messages.print_line'), mock.patch('dirdelta.messages.print_progress'):
            clouddirtreefactory._scan_drive_files_list(io.StringIO())
        self.assertEqual(service.files.return_value.list.call_args.kwargs['q'], 'trashed = false')

    def test_scan_shows_how_far_it_got(self):
        pages = [{'files': [{'id': 'a'}, {'id': 'b'}], 'nextPageToken': 'p2'}, {'files': [{'id': 'c'}]}]
        with mock.patch('dirdelta.driveapi.service', return_value=_fake_drive_service(pages)), \
             mock.patch('dirdelta.messages.print_line') as print_line, \
             mock.patch('dirdelta.messages.print_progress') as print_progress:
            clouddirtreefactory._scan_drive_files_list(io.StringIO(), expected_count=4)
        print_line.assert_called_once_with('Scanning Google Drive...')
        self.assertEqual([call.args[0] for call in print_progress.call_args_list], [
            'Read 0 of about 4 files and folders (0%)',
            'Read 2 of about 4 files and folders (50%)',
            'Read 3 files and folders',
        ])

    def test_scan_progress(self):
        progress = clouddirtreefactory._scan_progress
        self.assertEqual(progress(12420, 38455), 'Read 12,420 of about 38,455 files and folders (32%)')
        # Past what was expected, or with nothing expected, it's just the count
        self.assertEqual(progress(40000, 38455), 'Read 40,000 files and folders')
        self.assertEqual(progress(5, None), 'Read 5 files and folders')
        self.assertEqual(progress(5, 0), 'Read 5 files and folders')

    def test_refresh_expects_as_many_files_as_the_last_scan(self):
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, 'w') as f:
            f.write('{"myDriveRootId": "ROOT"}\n{"id": "a"}\n{"id": "b"}\n')
        with mock.patch('dirdelta.clouddirtreefactory._scan_drive_files_list') as scan:
            clouddirtreefactory._refresh_cache()
        self.assertEqual(scan.call_args.kwargs['expected_count'], 2)

    def test_first_refresh_expects_nothing(self):
        os.makedirs(os.path.dirname(self.cache))
        with mock.patch('dirdelta.clouddirtreefactory._scan_drive_files_list') as scan:
            clouddirtreefactory._refresh_cache()
        self.assertIsNone(scan.call_args.kwargs['expected_count'])

    def test_the_refresh_prompt_says_if_the_cache_is_stale(self):
        os.makedirs(os.path.dirname(self.cache))
        open(self.cache, 'w').close()
        for is_stale in (False, True):
            if is_stale:
                clouddirtreefactory.drivecache.mark_stale()
            with mock.patch('dirdelta.picker.pick_option',
                            return_value='Continue with old cloud files list cache') as pick_option:
                clouddirtreefactory.factory_interactive('cloud/mein')
            header = pick_option.call_args.kwargs['header']
            self.assertEqual('out of date' in header, is_stale, header)

    def test_a_refresh_makes_the_cache_fresh(self):
        os.makedirs(os.path.dirname(self.cache))
        clouddirtreefactory.drivecache.mark_stale()
        with mock.patch('dirdelta.clouddirtreefactory._scan_drive_files_list'):
            clouddirtreefactory._refresh_cache()
        self.assertFalse(clouddirtreefactory.drivecache.is_stale())

    def test_a_failed_refresh_leaves_it_stale(self):
        os.makedirs(os.path.dirname(self.cache))
        clouddirtreefactory.drivecache.mark_stale()
        with mock.patch('dirdelta.clouddirtreefactory._scan_drive_files_list', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                clouddirtreefactory._refresh_cache()
        self.assertTrue(clouddirtreefactory.drivecache.is_stale())

    def test_failed_refresh_keeps_the_old_cache(self):
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, 'w') as f:
            f.write('old\n')
        with mock.patch('dirdelta.clouddirtreefactory._scan_drive_files_list', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                clouddirtreefactory._refresh_cache()
        with open(self.cache) as f:
            self.assertEqual(f.read(), 'old\n')


if __name__ == '__main__':
    unittest.main()
