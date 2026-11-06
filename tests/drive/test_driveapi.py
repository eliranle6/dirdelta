import datetime
import os
import threading
import shutil
import tempfile
import time
import unittest
from unittest import mock

from google.oauth2.credentials import Credentials

from dirdelta.drive import driveapi


class RefreshTest(unittest.TestCase):
    """Google's own credentials, with made-up values, and only its request for a token faked"""
    def setUp(self):
        self.creds = driveapi._refreshed_one_at_a_time(Credentials(
            'old', refresh_token='made-up', token_uri='https://example.invalid', client_id='i', client_secret='s',
            expiry=datetime.datetime(2000, 1, 1)))
        self.tokens = iter(['new', 'newer'])
        self.grants = 0

    def grant(self, *_, **__):
        self.grants += 1
        time.sleep(0.05)
        return next(self.tokens), 'made-up', datetime.datetime(2100, 1, 1), {}, None

    def test_threads_needing_a_token_at_once_ask_for_one(self):
        with mock.patch('google.oauth2.reauth.refresh_grant', side_effect=self.grant):
            threads = [threading.Thread(target=self.creds.before_request, args=(mock.Mock(), 'GET', 'u', {})) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(self.grants, 1)
        self.assertEqual(self.creds.token, 'new')

    def test_a_token_rejected_while_it_looks_valid_is_still_refreshed(self):
        with mock.patch('google.oauth2.reauth.refresh_grant', side_effect=self.grant):
            self.creds.refresh(mock.Mock())
            self.assertTrue(self.creds.valid)
            self.creds.refresh(mock.Mock())
        self.assertEqual(self.grants, 2)
        self.assertEqual(self.creds.token, 'newer')

    def test_a_failed_refresh_lets_the_next_one_try(self):
        with mock.patch('google.oauth2.reauth.refresh_grant', side_effect=[OSError('no network'), ('new', 'made-up', datetime.datetime(2100, 1, 1), {}, None)]):
            with self.assertRaises(OSError):
                self.creds.refresh(mock.Mock())
            self.creds.refresh(mock.Mock())
        self.assertEqual(self.creds.token, 'new')


class ServiceTest(unittest.TestCase):
    """Logging in, with Google's classes faked, and the token in a temp dir"""
    def setUp(self):
        token_dir = tempfile.mkdtemp(prefix='dirstuff-token-')
        self.addCleanup(shutil.rmtree, token_dir, ignore_errors=True)
        self.token_path = os.path.join(token_dir, 'token.json')
        with open(self.token_path, 'w') as f:
            f.write('{"saved": true}')
        patchers = {
            'credentials': mock.patch('dirdelta.drive.driveapi.Credentials'),
            'flow': mock.patch('dirdelta.drive.driveapi.InstalledAppFlow'),
            'build': mock.patch('dirdelta.drive.driveapi.build'),
        }
        for patcher in [mock.patch('dirdelta.drive.driveapi.TOKEN_PATH', self.token_path),
                        mock.patch('dirdelta.drive.driveapi._local', threading.local()),
                        mock.patch('dirdelta.drive.driveapi._shared_credentials', None),
                        mock.patch('dirdelta.ui.messages.print_line')]:
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

    def test_each_thread_has_its_own_service_with_one_login(self):
        self.saved.valid = True
        self.build.side_effect = lambda *_, **__: mock.Mock()
        services = [driveapi.service()]
        thread = threading.Thread(target=lambda: services.append(driveapi.service()))
        thread.start()
        thread.join()
        self.assertIsNot(services[0], services[1])
        self.credentials.from_authorized_user_file.assert_called_once()

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


class GetUrlTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(driveapi, 'service')
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('google_auth_httplib2.AuthorizedHttp')
        self.http = patcher.start()
        self.addCleanup(patcher.stop)

    def test_what_fails_is_an_oserror(self):
        self.http.return_value.request.return_value = (mock.Mock(status=404), b'')
        with self.assertRaises(OSError):
            driveapi.get_url('https://example.invalid/t')
        self.http.return_value.request.side_effect = OSError('down')
        with self.assertRaises(OSError):
            driveapi.get_url('https://example.invalid/t')
