"""Using a newer copy from Drive, at a sync's start (check())"""
import json
import os
import tempfile

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.drivemeta.lookup import folder_id_of, found_copy, note_user
from dirdelta.drive.drivemeta.names import FILE_NAME, HEADER_KEY, NUM_RETRIES, USED


def check(folder_path):
    """Put the copy of folder_path's list kept in Drive (see the module's doc) in the cache, if it's
    newer than the cache's. Returns USED if it was, else None. Raises HttpError or OSError if Drive
    can't be asked."""
    note_user()
    folder_id = folder_id_of(folder_path)
    if folder_id is None:
        return None
    meta, found = found_copy(folder_id)
    if found is None or found.get('modifiedTime') == (drivecache.uploaded(folder_path) or {}).get('modified'):
        return None
    modified = drivecache.modified_time(found)
    local = drivecache.updated(folder_path)
    if modified is None or (local is not None and modified <= local):
        return None
    with tempfile.TemporaryDirectory(prefix='dirdelta-meta-') as temp_dir:
        path = os.path.join(temp_dir, FILE_NAME)
        request = driveapi.service().files().get_media(fileId=found['id'])
        with open(path, 'wb') as local_file:
            local_file.write(request.execute(num_retries=NUM_RETRIES))
        with open(path) as local_file:
            lines = [json.loads(line) for line in local_file if line.startswith('{')]
    header = lines[0].get(HEADER_KEY) if lines else None
    if (not isinstance(header, dict) or header.get('folderId') != folder_id or
            header.get('rootId') != drivecache.root_id()):
        # Not a list of this folder (or of this Drive)
        return None
    drivecache.replace_under(folder_id, lines[1:] + [meta, found], header['rootId'])
    drivecache.note_updated(folder_path, modified)
    drivecache.note_uploaded(folder_path, found['modifiedTime'], modified)
    return USED
