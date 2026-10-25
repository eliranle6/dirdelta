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
        with mock.patch('dirdelta.clouddirtreefactory.Credentials') as credentials, \
             mock.patch('dirdelta.clouddirtreefactory.build', return_value=_fake_drive_service(pages)), \
             mock.patch('os.path.exists', return_value=True), mock.patch('builtins.print'):
            credentials.from_authorized_user_file.return_value.valid = True
            clouddirtreefactory._scan_drive_files_list(out)
        self.assertEqual([json.loads(line)['id'] for line in out.getvalue().splitlines()], ['a', 'b', 'c'])

    def test_rejected_token_refresh_logs_in_again(self):
        token_dir = tempfile.mkdtemp(prefix='dirstuff-token-')
        self.addCleanup(shutil.rmtree, token_dir, ignore_errors=True)
        token_path = os.path.join(token_dir, 'token.json')
        with mock.patch('dirdelta.clouddirtreefactory.TOKEN_PATH', token_path), \
             mock.patch('dirdelta.clouddirtreefactory.Credentials') as credentials, \
             mock.patch('dirdelta.clouddirtreefactory.InstalledAppFlow') as flow, \
             mock.patch('dirdelta.clouddirtreefactory.build', return_value=_fake_drive_service([{'files': []}])), \
             mock.patch('os.path.exists', return_value=True), mock.patch('builtins.print'):
            saved = credentials.from_authorized_user_file.return_value
            saved.valid = False
            saved.refresh.side_effect = clouddirtreefactory.RefreshError('invalid_grant')
            fresh = flow.from_client_secrets_file.return_value.run_local_server.return_value
            fresh.to_json.return_value = '{"fresh": true}'
            clouddirtreefactory._scan_drive_files_list(io.StringIO())
        flow.from_client_secrets_file.return_value.run_local_server.assert_called_once()
        with open(token_path) as f:
            self.assertEqual(f.read(), '{"fresh": true}')

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
