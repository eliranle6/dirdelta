"""Sending mail from the user's Gmail (send()), through the Gmail API with dirdelta's Google client
(driveapi's CREDENTIALS_PATH). Its login is apart from Drive's: TOKEN_PATH, allowed only to send
(gmail.send: it can't read the user's mail), approved in the browser the first time."""
import base64
import os
from email.message import EmailMessage

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from dirdelta.drive import driveapi
from dirdelta.ui import messages

TOKEN_PATH = os.path.join(driveapi.SECRETS_DIR, 'gmail_token.json')
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


class MailError(Exception):
    """Mail that couldn't be sent: not approved, Gmail's API off for the client's project, no network..."""


def send(to, subject, body):
    """Email body (plain text) to the address to, from the Gmail account logged in to. Raises
    MailError if it can't."""
    message = EmailMessage()
    message['To'] = to
    message['Subject'] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
    try:
        service = build('gmail', 'v1', credentials=_credentials(), cache_discovery=False)
        service.users().messages().send(userId='me', body={'raw': raw}).execute(num_retries=3)
    except HttpError as error:
        raise MailError(error.reason or str(error))
    except (GoogleAuthError, OSError, ValueError) as error:
        raise MailError(str(error))


def _credentials():
    """The saved login, refreshed if it expired, else a new one, approved in the browser (and saved,
    readable only by the user)"""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
        if not creds.has_scopes(SCOPES):
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            # Revoked, or expired (an app in "Testing" gets 7-day ones)
            creds = None
    if not creds or not creds.valid:
        messages.print_line("Sending mail needs your OK, once: approve it in the browser...")
        creds = InstalledAppFlow.from_client_secrets_file(driveapi.CREDENTIALS_PATH, SCOPES).run_local_server(port=0)
    with open(os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as token:
        token.write(creds.to_json())
    return creds
