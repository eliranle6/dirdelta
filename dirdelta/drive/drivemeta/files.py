"""Any file of a Drive replica's META_DIR, read and written by name (read_text(), write_text()), as its file
list is (uploading.py): e.g. its sync history (synchistory.py)"""
import io
import os
import tempfile

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.drivemeta.lookup import _query, folder_id_of
from dirdelta.drive.drivemeta.names import NUM_RETRIES
from dirdelta.trees import paths


def _meta_folder(folder_id, make=False):
    """The replica's META_DIR's metadata (made, with make, if Drive has none), or None"""
    folders = _query("name = '%s' and '%s' in parents and mimeType = '%s' and trashed = false" %
                     (paths.META_DIR, folder_id, drivecache.FOLDER_MIME_TYPE))
    if folders:
        return folders[0]
    if not make:
        return None
    meta = driveapi.service().files().create(body={'name': paths.META_DIR, 'mimeType': drivecache.FOLDER_MIME_TYPE,
                                                   'parents': [folder_id]},
                                             fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
    drivecache.add(dict(meta, parents=[folder_id]))
    return meta


def _file_in(meta, name):
    found = _query("name = '%s' and '%s' in parents and trashed = false" % (name, meta['id']))
    return found[0] if found else None


def read_text(folder_path, name):
    """The text of META_DIR/name in the Drive replica at folder_path (a path in Drive), or None if it has
    none. Raises HttpError or OSError if it can't be read."""
    folder_id = folder_id_of(folder_path)
    meta = _meta_folder(folder_id) if folder_id else None
    found = _file_in(meta, name) if meta else None
    if found is None:
        return None
    data = io.BytesIO()
    downloader = MediaIoBaseDownload(data, driveapi.service().files().get_media(fileId=found['id']))
    is_done = False
    while not is_done:
        _, is_done = downloader.next_chunk(num_retries=NUM_RETRIES)
    return data.getvalue().decode('utf-8', 'replace')


def write_text(folder_path, name, text):
    """Make META_DIR/name in the Drive replica at folder_path text (a new version, if it's there; META_DIR
    made, if it isn't). Raises HttpError or OSError if it can't be written (or there's no such folder)."""
    folder_id = folder_id_of(folder_path)
    if folder_id is None:
        raise OSError("Drive has no folder %s (as of its list)" % (folder_path,))
    meta = _meta_folder(folder_id, make=True)
    found = _file_in(meta, name)
    service = driveapi.service()
    with tempfile.TemporaryDirectory(prefix='dirdelta-meta-') as temp_dir:
        path = os.path.join(temp_dir, name)
        with open(path, 'w', encoding='utf-8') as local_file:
            local_file.write(text)
        media = MediaFileUpload(path, mimetype='application/json')
        if found is None:
            md = service.files().create(body={'name': name, 'parents': [meta['id']]}, media_body=media,
                                        fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
        else:
            md = service.files().update(fileId=found['id'], media_body=media,
                                        fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
    drivecache.add(dict(md, parents=[meta['id']]))
