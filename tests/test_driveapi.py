import os
import shutil
import tempfile
import unittest
from unittest import mock

from dirdelta import driveapi


class ServiceTest(unittest.TestCase):
    """Logging in, with Google's classes faked, and the token in a temp dir"""
    def setUp(self):
        token_dir = tempfile.mkdtemp(prefix='dirstuff-token-')
        self.addCleanup(shutil.rmtree, token_dir, ignore_errors=True)
        self.token_path = os.path.join(token_dir, 'token.json')
        with open(self.token_path, 'w') as f:
            f.write('{"saved": true}')
        patchers = {
            'credentials': mock.patch('dirdelta.driveapi.Credentials'),
            'flow': mock.patch('dirdelta.driveapi.InstalledAppFlow'),
            'build': mock.patch('dirdelta.driveapi.build'),
        }
        for patcher in [mock.patch('dirdelta.driveapi.TOKEN_PATH', self.token_path),
                        mock.patch('dirdelta.driveapi._service', None),
                        mock.patch('dirdelta.messages.print_line')]:
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, patcher in patchers.items():
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.saved = self.credentials.from_authorized_user_file.return_value
        self.saved.has_scopes.return_value = True
        self.fresh = self.flow.from_client_secrets_file.return_value.run_local_server.return_value
        self.fresh.to_json.return_value = '{"fresh": true}'

    def token(self):
        with open(self.token_path) as f:
            return f.read()

    def test_a_valid_saved_login_is_used(self):
        self.saved.valid = True
        self.assertIs(driveapi.service(), self.build.return_value)
        self.build.assert_called_once_with('drive', 'v3', credentials=self.saved)
        self.flow.from_client_secrets_file.assert_not_called()

    def test_the_service_is_made_once(self):
        self.saved.valid = True
        self.assertIs(driveapi.service(), driveapi.service())
        self.build.assert_called_once()

    def test_an_expired_login_is_refreshed_and_saved(self):
        self.saved.valid = False
        self.saved.refresh.side_effect = lambda request: setattr(self.saved, 'valid', True)
        self.saved.to_json.return_value = '{"refreshed": true}'
        driveapi.service()
        self.flow.from_client_secrets_file.assert_not_called()
        self.assertEqual(self.token(), '{"refreshed": true}')

    def test_rejected_token_refresh_logs_in_again(self):
        self.saved.valid = False
        self.saved.refresh.side_effect = driveapi.RefreshError('invalid_grant')
        driveapi.service()
        self.flow.from_client_secrets_file.return_value.run_local_server.assert_called_once()
        self.assertEqual(self.token(), '{"fresh": true}')

    def test_a_login_without_the_scopes_logs_in_again(self):
        # E.g. from when dirdelta only listed files
        self.saved.valid = True
        self.saved.has_scopes.return_value = False
        driveapi.service()
        self.saved.has_scopes.assert_called_once_with(driveapi.SCOPES)
        self.flow.from_client_secrets_file.assert_called_once_with(driveapi.CREDENTIALS_PATH,
                                                                   driveapi.SCOPES)
        self.assertEqual(self.token(), '{"fresh": true}')

    def test_no_saved_login_logs_in(self):
        os.remove(self.token_path)
        driveapi.service()
        self.credentials.from_authorized_user_file.assert_not_called()
        self.assertEqual(self.token(), '{"fresh": true}')
