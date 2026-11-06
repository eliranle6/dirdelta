"""dirdelta's connection to the Google Drive API (service()), logged in with the OAuth secrets in
SECRETS_DIR: credentials.json (the OAuth client) and token.json (the user's login, written after
logging in in the browser)."""
import os.path
import threading

import google_auth_httplib2
import httplib2

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from dirdelta.ui import messages

# secrets/ at the repo root when running from source; an installed copy needs DIRDELTA_SECRETS_DIR
SECRETS_DIR = os.environ.get(
    'DIRDELTA_SECRETS_DIR',
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'secrets'))
TOKEN_PATH = os.path.join(SECRETS_DIR, 'token.json')
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, 'credentials.json')

# All of Drive: listing it, and downloading, uploading and trashing files. A saved login without
# them (e.g. from when dirdelta only listed files) makes the user log in again.
SCOPES = ['https://www.googleapis.com/auth/drive']

# Each thread's service (the client's HTTP connection isn't thread-safe, so uploads in parallel each
# need their own), and the login they share, once logged in
_local = threading.local()
_shared_credentials = None
_login_lock = threading.Lock()


def user_name():
    """The name of the account logged in to, as its email address's first part (or its whole name)"""
    user = service().about().get(fields='user(emailAddress,displayName)').execute(num_retries=3).get('user', {})
    return (user.get('emailAddress') or '').split('@')[0] or user.get('displayName')


def service():
    """The Drive API (v3) service of this thread, logging in first if needed (once, for all threads:
    in the browser, unless there's a saved login with SCOPES)"""
    global _shared_credentials
    if getattr(_local, 'service', None) is None:
        with _login_lock:
            if _shared_credentials is None:
                _shared_credentials = _refreshed_one_at_a_time(_credentials())
        _local.service = build('drive', 'v3', credentials=_shared_credentials)
    return _local.service


def get_url(url):
    """The contents at url, got with the login's credentials (e.g. a file's thumbnailLink, which Drive
    serves only to its owner). Raises OSError if it can't."""
    service()
    try:
        response, content = google_auth_httplib2.AuthorizedHttp(_shared_credentials, httplib2.Http(timeout=30)).request(url)
    except (httplib2.HttpLib2Error, OSError) as error:
        raise OSError("Can't get %s: %s" % (url, error))
    if response.status != 200:
        raise OSError("Can't get %s: HTTP %s" % (url, response.status))
    return content


def _refreshed_one_at_a_time(creds):
    """creds, shared by the threads, with its refresh() under a lock (Google's has none): a thread
    that waited for another's refresh uses the token that got, rather than asking for one more. It
    goes by the token, not by whether it's valid: a token Drive rejected looks valid until refreshed.
    Returns creds."""
    lock = threading.Lock()
    refresh = creds.refresh

    def refreshed_once(request):
        token_seen = creds.token
        with lock:
            if creds.token == token_seen:
                refresh(request)
    creds.refresh = refreshed_once
    return creds


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
