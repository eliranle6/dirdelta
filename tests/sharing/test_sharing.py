"""Handing the user a page's address: a QR code on a screen, and an email (dirdelta.sharing)"""
import base64
import email
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real caches and settings left alone)
from dirdelta.sharing import gmail
from dirdelta.sharing import link
from dirdelta.sharing import qr

URL = 'http://10.0.0.8:8765/?k=secret'
ANSI = re.compile('\033\\[[0-9;]*m')


class ShareTest(unittest.TestCase):
    def setUp(self):
        # Never the real token, nor a browser
        self.secrets = tempfile.mkdtemp(prefix='dirdelta-test-secrets-')
        self.addCleanup(shutil.rmtree, self.secrets)
        patcher = mock.patch.object(gmail, 'TOKEN_PATH', os.path.join(self.secrets, 'gmail_token.json'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.shown = mock.patch('dirdelta.ui.messages.show').start()
        self.addCleanup(mock.patch.stopall)
        mock.patch('dirdelta.ui.messages.print_line').start()
        mock.patch('dirdelta.drive.driveapi.user_email', return_value='me@example.com').start()

    def shown_lines(self):
        (title, lines, _label), _ = self.shown.call_args
        return title, [ANSI.sub('', line) for line in lines]

    def test_the_address_is_emailed_to_the_drive_account_and_shown_as_a_qr_code(self):
        with mock.patch('dirdelta.sharing.gmail.send') as send:
            link.share(URL, "Sort the imported photos")
        to, subject, body = send.call_args[0]
        self.assertEqual('me@example.com', to)
        self.assertIn("Sort the imported photos", subject)
        self.assertIn(URL, body)
        title, lines = self.shown_lines()
        self.assertEqual("Sort the imported photos", title)
        self.assertIn(URL, lines)
        self.assertIn("Emailed to me@example.com too.", lines)
        for line in qr.lines(URL):
            self.assertIn(ANSI.sub('', line), lines)

    def test_when_it_cant_be_emailed_the_screen_says_why_and_still_shows_the_code(self):
        with mock.patch('dirdelta.sharing.gmail.send', side_effect=gmail.MailError("Gmail API has not been used")):
            link.share(URL, "Sort the imported photos")
        _, lines = self.shown_lines()
        self.assertIn("Not emailed: Gmail API has not been used", lines)
        self.assertIn(URL, lines)

    def test_send_hands_gmail_the_message(self):
        service = mock.MagicMock()
        with mock.patch.object(gmail, '_credentials'), mock.patch.object(gmail, 'build', return_value=service):
            gmail.send('me@example.com', "Subject", "The address: " + URL)
        _, kwargs = service.users().messages().send.call_args
        self.assertEqual('me', kwargs['userId'])
        message = email.message_from_bytes(base64.urlsafe_b64decode(kwargs['body']['raw']))
        self.assertEqual('me@example.com', message['To'])
        self.assertIn(URL, message.get_payload(decode=True).decode())


class QRTest(unittest.TestCase):
    def test_a_code_is_one_block_of_equal_lines_about_as_tall_as_it_is_wide(self):
        lines = [ANSI.sub('', line) for line in qr.lines(URL)]
        widths = {len(line) for line in lines}
        self.assertEqual(1, len(widths))
        # Two rows of modules to a line
        self.assertLessEqual(abs(widths.pop() - 2 * len(lines)), 1)

    def test_different_addresses_get_different_codes(self):
        self.assertNotEqual(qr.lines(URL), qr.lines(URL + 'x'))


if __name__ == '__main__':
    unittest.main()
