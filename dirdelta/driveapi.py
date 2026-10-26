"""dirdelta's connection to the Google Drive API (service()), logged in with the OAuth secrets in
SECRETS_DIR: credentials.json (the OAuth client) and token.json (the user's login, written after
logging in in the browser)."""
import os.path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from dirdelta import messages

# secrets/ at the repo root when running from source; an installed copy needs DIRDELTA_SECRETS_DIR
SECRETS_DIR = os.environ.get(
    'DIRDELTA_SECRETS_DIR',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'secrets'))
TOKEN_PATH = os.path.join(SECRETS_DIR, 'token.json')
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, 'credentials.json')

# All of Drive: listing it, and downloading, uploading and trashing files. A saved login without
# them (e.g. from when dirdelta only listed files) makes the user log in again.
SCOPES = ['https://www.googleapis.com/auth/drive']

# The service, once logged in
_service = None


def service():
    """The Drive API (v3) service, logging in first if needed (in the browser, unless there's a
    saved login with SCOPES)"""
    global _service
    if _service is None:
        _service = build('drive', 'v3', credentials=_credentials())
    return _service


def _credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        # With the scopes it was saved with, to see if they're enough
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
        if not creds.has_scopes(SCOPES):
            messages.print_line("Drive needs a new login, to change files too, logging in...")
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as error:
            # The refresh token was revoked or expired (an app in "Testing" gets 7-day ones)
            messages.print_line('Saved Drive login was rejected (%s), logging in again...' % (error,))
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open(TOKEN_PATH, 'w') as token:
        token.write(creds.to_json())
    return creds
