"""Uploading the cache's list of a folder to its copy (upload())"""
import json
import os
import tempfile

from googleapiclient.http import MediaFileUpload

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.drivemeta.lookup import _folder_id, _found
from dirdelta.drive.drivemeta.names import FILE_NAME, HEADER_KEY, NUM_RETRIES
from dirdelta.trees import paths


def upload(folder_path):
    """Upload the cache's list of folder_path to its META_DIR/FILE_NAME in Drive (making them, if
    there are none), and note it (drivecache.note_uploaded()). Raises HttpError or OSError if it
    can't."""
    folder_id = _folder_id(folder_path)
    if folder_id is None:
        return
    as_of = drivecache.updated(folder_path)
    meta, found = _found(folder_id)
    service = driveapi.service()
    if meta is None:
        meta = service.files().create(body={'name': paths.META_DIR, 'mimeType': drivecache.FOLDER_MIME_TYPE,
                                            'parents': [folder_id]},
                                      fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
        meta = dict(meta, parents=[folder_id])
        drivecache.add(meta)
    header = {HEADER_KEY: {'folder': '/' + '/'.join(paths.components(folder_path)), 'folderId': folder_id,
                           'rootId': drivecache.root_id()}}
    with tempfile.TemporaryDirectory(prefix='dirdelta-meta-') as temp_dir:
        path = os.path.join(temp_dir, FILE_NAME)
        with open(path, 'w') as local_file:
            for md in [header] + drivecache.under(folder_id, left_out={meta['id']}):
                local_file.write(json.dumps(md) + '\n')
        media = MediaFileUpload(path, mimetype='application/json')
        if found is None:
            md = service.files().create(body={'name': FILE_NAME, 'parents': [meta['id']]}, media_body=media,
                                        fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
        else:
            md = service.files().update(fileId=found['id'], media_body=media,
                                        fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
    md = dict(md, parents=[meta['id']])
    drivecache.add(md)
    drivecache.note_uploaded(folder_path, md.get('modifiedTime'), as_of)
