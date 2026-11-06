"""Reading a Drive folder anew into the cache"""
import contextlib

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import MAX_FOLDERS_PER_QUERY, MAX_LISTED, NUM_RETRIES
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.util import text


@contextlib.contextmanager
def _changing_both(folder_path, other_path):
    """Around a change dirdelta makes in Drive under both folders (maybe the same one): see
    drivecache.changing()"""
    with drivecache.changing(folder_path):
        with drivecache.changing(other_path):
            yield


def refresh_cache(folder_path):
    """Read the folder at folder_path (a path in Drive, like /eliran; / is all of My Drive) anew from
    Drive, and put it in the cache, in place of what the cache had under it (making the cache, if
    there's none). The folder is found by its path's names, a request a level, then what's in it is
    read, a level of folders at a time (MAX_FOLDERS_PER_QUERY folders a request, one request at a
    time). The rest of the cache isn't read again. Raises HttpError if Drive can't be asked, and
    drivecache.DriveCacheError if it has no such folder (or two); either way (and on Ctrl-C), the
    cache is as it was."""
    folder_path = '/' + '/'.join(paths.components(folder_path))
    root_id = driveapi.service().files().get(fileId='root', fields='id').execute(
        num_retries=NUM_RETRIES)['id']
    # The folders on the way, so the cache has them (as they're named now)
    on_the_way = []
    folder_id = root_id
    messages.print_line("Reading %s from Google Drive..." % (paths.join_cloud(folder_path),))
    path = ''
    for name in paths.components(folder_path):
        path += '/' + name
        found = list(_list("name = '%s' and '%s' in parents and mimeType = '%s' and trashed = false" %
                           (_quoted(name), folder_id, drivecache.FOLDER_MIME_TYPE),
                           drivecache.FILE_FIELDS))
        if not found:
            raise drivecache.DriveCacheError("Google Drive has no folder %s" % (path,))
        if len(found) > 1:
            raise drivecache.DriveCacheError("Google Drive has %d folders named %s: rename them in "
                                             "Drive (a folder's name must be its own)" % (len(found), path))
        on_the_way.append(found[0])
        folder_id = found[0]['id']

    expected_count = drivecache.count_under(folder_path)
    items = []
    folder_ids = [folder_id]
    messages.print_progress(_read_progress(0, expected_count))
    while folder_ids:
        next_folder_ids = []
        for start in range(0, len(folder_ids), MAX_FOLDERS_PER_QUERY):
            query = "(%s) and trashed = false" % (' or '.join(
                "'%s' in parents" % (cloud_id,)
                for cloud_id in folder_ids[start:start + MAX_FOLDERS_PER_QUERY]),)
            for md in _list(query, drivecache.FILE_FIELDS):
                items.append(md)
                if md.get('mimeType') == drivecache.FOLDER_MIME_TYPE:
                    next_folder_ids.append(md['id'])
            messages.print_progress(_read_progress(len(items), expected_count))
        folder_ids = next_folder_ids
    # Done: the count, without the last refresh's
    messages.print_progress(_read_progress(len(items), None))

    drivecache.replace_under(folder_id, on_the_way + items, root_id)
    drivecache.mark_fresh(folder_path)
    drivecache.note_updated(folder_path)


def _read_progress(count, expected_count):
    """How far reading got, after count files (and folders), expecting about expected_count (or
    None, if not known)"""
    if expected_count and count < expected_count:
        return "Read %s of about %s files and folders (%d%%)" % (
            format(count, ','), format(expected_count, ','), 100 * count // expected_count)
    return "Read %s files and folders" % (format(count, ','),)


def _quoted(name):
    """name, to put between quotes in a Drive query"""
    return name.replace('\\', '\\\\').replace("'", "\\'")


def _list(query, fields='id, parents'):
    """The files and folders (their fields) that Drive lists for query, page by page"""
    page_token = None
    while True:
        response = driveapi.service().files().list(
            q=query, fields='nextPageToken, files(%s)' % (fields,), pageSize=1000,
            pageToken=page_token).execute(num_retries=NUM_RETRIES)
        yield from response.get('files', [])
        page_token = response.get('nextPageToken')
        if not page_token:
            return


def _is_under(relpath, folder):
    return relpath.startswith(folder + '/')


def _listed(items):
    """Lines listing the first MAX_LISTED of items, indented, and how many more there are"""
    return text.listed(["  %s" % (item,) for item in items], MAX_LISTED)
