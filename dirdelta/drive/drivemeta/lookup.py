"""Finding a folder's copy in Drive"""
from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.drivemeta.names import FILE_NAME, NUM_RETRIES
from dirdelta.trees import paths


def _query(query, fields='files(%s)' % (drivecache.FILE_FIELDS,)):
    return driveapi.service().files().list(q=query, fields=fields, pageSize=10).execute(
        num_retries=NUM_RETRIES).get('files', [])


def _folder_id(folder_path):
    """The Drive id of the folder at folder_path (a path in Drive), as the cache has it, or None"""
    try:
        for entry in drivecache.entries(folder_path):
            return entry.cloud_id
    except drivecache.DriveCacheError:
        pass
    return None


def _found(folder_id):
    """(META_DIR's metadata, FILE_NAME's in it), each None if Drive has none, by two requests"""
    folders = _query("name = '%s' and '%s' in parents and mimeType = '%s' and trashed = false" %
                     (paths.META_DIR, folder_id, drivecache.FOLDER_MIME_TYPE))
    if not folders:
        return None, None
    files = _query("name = '%s' and '%s' in parents and trashed = false" % (FILE_NAME, folders[0]['id']))
    return folders[0], (files[0] if files else None)


def _note_user():
    """Note the account's user name, once, for the screens (see replicanames.py); only to say it:
    without it, they say less"""
    if drivecache.user() is None:
        try:
            drivecache.note_user(driveapi.user_name())
        except Exception:
            pass
