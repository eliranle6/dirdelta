import json
import os.path

from dirdelta import clouddirtree
from dirdelta import driveapi
from dirdelta import drivecache
from dirdelta import messages
from dirdelta import picker


def factory_interactive(rootpath):
    # Make sure cloud files list cache exists
    if os.path.exists(drivecache.FILE_LIST_CACHE):

        # Ask user whether to refresh files list cache
        if _does_user_want_to_refresh_cache(rootpath):
            _refresh_cache()

    # Create files list cache as it doesn't exist
    else:
        os.makedirs(os.path.dirname(drivecache.FILE_LIST_CACHE), exist_ok=True)
        _refresh_cache()

    return clouddirtree.factory(rootpath)


def _does_user_want_to_refresh_cache(rootpath):
    OPTION_REFRESH = 'Refresh cloud files list cache'
    OPTION_NO_REFRESH = 'Continue with old cloud files list cache'
    options = [OPTION_REFRESH, OPTION_NO_REFRESH]
    header = ''
    if drivecache.is_stale():
        header = ("The cloud files list cache is out of date: dirdelta changed Google Drive after it "
                  "was made.\nRefresh it to see those changes.")
    return picker.pick_option(options, header=header) == OPTION_REFRESH


def _refresh_cache():
    # Scan into a temporary file first, so a failed scan doesn't leave a truncated cache behind
    tmp_path = drivecache.FILE_LIST_CACHE + '.tmp'
    # Drive can't say how many files it has, but the last scan can, roughly
    expected_count = drivecache.count_entries() if os.path.exists(drivecache.FILE_LIST_CACHE) else None
    with open(tmp_path, 'w') as fp:
        _scan_drive_files_list(outfile=fp, expected_count=expected_count)
    os.replace(tmp_path, drivecache.FILE_LIST_CACHE)
    drivecache.mark_fresh()


def _scan_progress(count, expected_count):
    """How far scanning got, after count files (and folders), expecting about expected_count (or
    None, if not known)"""
    if expected_count and count < expected_count:
        return "Read %s of about %s files and folders (%d%%)" % (
            format(count, ','), format(expected_count, ','), 100 * count // expected_count)
    return "Read %s files and folders" % (format(count, ','),)


def _scan_drive_files_list(outfile, expected_count=None):
    service = driveapi.service()

    # My Drive's root folder isn't listed itself, so write down its id
    root = service.files().get(fileId='root', fields='id').execute()
    outfile.write(json.dumps({drivecache.ROOT_ID_KEY: root['id']}) + '\n')

    # Call the Drive v3 API
    messages.print_line("Scanning Google Drive...")
    page_token = None
    count = 0
    messages.print_progress(_scan_progress(count, expected_count))
    while True:
        req = service.files().list(
            pageSize=1000,
            q='trashed = false',
            fields="nextPageToken, files(id, name, parents, kind, size, mimeType, sha256Checksum)",
            pageToken=page_token)
        results = req.execute()

        page_items = results.get('files', [])
        for item in page_items:
            outfile.write(json.dumps(item) + '\n')
        count += len(page_items)

        page_token = results.get('nextPageToken', None)
        if page_token is None:
            break
        messages.print_progress(_scan_progress(count, expected_count))

    # Done: the count, without the last scan's
    messages.print_progress(_scan_progress(count, None))

    #except HttpError as error:
    #    # TODO(developer) - Handle errors from drive API.
    #    print(f'An error occurred: {error}')
