import json
import os.path
import shutil
import tempfile

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import clouddirtree
import treepicker


SECRETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'secrets')
TOKEN_PATH = os.path.join(SECRETS_DIR, 'token.json')
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, 'credentials.json')


def factory_interactive(rootpath):
    # Make sure cloud files list cache exists
    if os.path.exists(clouddirtree.FILE_LIST_CACHE):

        # Ask user whether to refresh files list cache
        if _does_user_want_to_refresh_cache(rootpath):
            _refresh_cache()

    # Create files list cache as it doesn't exist
    else:
        os.makedirs(os.path.dirname(clouddirtree.FILE_LIST_CACHE), exist_ok=True)
        _refresh_cache()


    return CloudDirTree(path_in_cloud)


def _does_user_want_to_refresh_cache(rootpath):
    OPTION_REFRESH = 'Refresh cloud files list cache'
    OPTION_NO_REFRESH = 'Continue with old cloud files list cache'
    options = [OPTION_REFRESH, OPTION_NO_REFRESH]
    picker = treepicker.optionpicker.OptionPickerByMenuTraverse(options)
    option = picker.pick_one()
    return option == OPTION_REFRESH


def _refresh_cache():
    with tempfile.TemporaryFile() as fp:
        _scan_drive_files_list(outfile=fp)

    shutil.copy(fp.name, clouddirtree.FILE_LIST_CACHE)


def _scan_drive_files_list(outfile):
    # If modifying these scopes, delete the file token.json.
    SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']

    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    #try:
    service = build('drive', 'v3', credentials=creds)

    # Call the Drive v3 API
    page_token = None
    iter_cnt = 0
    while True:
        req = service.files().list(
            pageSize=1000,
            fields="nextPageToken, files(id, name, parents, kind, size, mimeType, sha256Checksum)",
            pageToken=page_token)
        results = req.execute()

        page_items = results.get('files', [])
        print(f'#items in page: {len(page_items)}')
        for item in page_items:
            outfile.write(json.dumps(item) + '\n')

        page_token = results.get('nextPageToken', None)
        if page_token is None:
            break

        iter_cnt += 1

    #except HttpError as error:
    #    # TODO(developer) - Handle errors from drive API.
    #    print(f'An error occurred: {error}')
