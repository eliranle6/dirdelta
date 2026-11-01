"""A Drive replica's file list, kept in it too: FILE_NAME in its paths.META_DIR (cloud/X/meta/
files.jsonl), so another machine (or this one, with an older cache) can use it rather than read
the whole folder from Drive again. Its first line is a header (HEADER_KEY: the folder's path, its
id, My Drive's root id), then a line per file and folder under it, as the cache has them
(drivecache.py), without what's in META_DIR.

At a sync's (or a sort's) start, check() asks Drive (two requests) for the copy's modifiedTime: if
it's newer than when this machine's cache of the folder was last updated (drivecache.updated()),
and not the copy this cache made, it's downloaded into the cache. While the sync goes on, an
Uploader uploads the cache's list again whenever it changed since (every UPLOAD_INTERVAL seconds at
most, on a thread of its own, and once more when the sync ends): not after each change (each would
be an upload of the whole list), and not left for a question at the end, which a sync cut off would
never get to. Nothing is uploaded in a dry run."""
import contextlib
import json
import os
import tempfile
import threading

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from dirdelta import driveapi
from dirdelta import drivecache
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker

FILE_NAME = 'files.jsonl'
HEADER_KEY = 'dirdeltaFileList'
# How often the Uploader looks whether the list changed since it was last uploaded, in seconds
UPLOAD_INTERVAL = 60
NUM_RETRIES = 3

# What check() did: put Drive's copy in the cache (it was newer), or nothing (the same, or none
# there, or the cache's is newer: the Uploader will upload it)
USED = 'used'


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


def check(folder_path):
    """Put the copy of folder_path's list kept in Drive (see the module's doc) in the cache, if it's
    newer than the cache's. Returns USED if it was, else None. Raises HttpError or OSError if Drive
    can't be asked."""
    folder_id = _folder_id(folder_path)
    if folder_id is None:
        return None
    meta, found = _found(folder_id)
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


class Uploader(object):
    """Uploads the cache's list of a Drive replica's folder (see upload()) whenever it changed
    since the last upload, every UPLOAD_INTERVAL seconds at most, on a thread of its own, from
    start() until stop() (which uploads once more, if it changed). What goes wrong is written to
    picker.ERRORS_LOG (and tried again next time), not on the screen."""
    def __init__(self, folder_path):
        self.folder_path = folder_path
        self._stopping = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stopping.wait(UPLOAD_INTERVAL):
            try:
                self.upload_if_changed()
            except Exception:
                picker.log_error()

    def is_changed(self):
        """Whether the cache's list changed since it was last uploaded (or it never was)"""
        updated = drivecache.updated(self.folder_path)
        uploaded = drivecache.uploaded(self.folder_path)
        if uploaded is None:
            return True
        return updated is not None and (uploaded.get('as_of') is None or updated > uploaded['as_of'])

    def upload_if_changed(self):
        """Upload it, if it changed since (not in a dry run). Returns whether it was uploaded."""
        with self._lock:
            if dryrun.DRYRUN or not self.is_changed():
                return False
            upload(self.folder_path)
            return True

    def stop(self):
        """Stop, uploading it once more if it changed since. Raises as upload() does."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join()
        return self.upload_if_changed()


@contextlib.contextmanager
def kept(replicas):
    """While a sync or a sort of replicas ([(a replica's path, its tree, or None if it's not made
    yet)]) goes on: each Drive one's list is checked against the copy in Drive first (check(); a
    tree is rebuilt from the cache if that was newer), and uploaded (an Uploader) as it changes, and
    once more at the end"""
    uploaders = []
    for path, tree in replicas:
        if not paths.is_cloud_path(path):
            continue
        folder_path = paths.path_in_cloud(path)
        try:
            if check(folder_path) == USED:
                if tree is not None:
                    tree.reload_from_cache()
                messages.print_line("Using the file list of %s kept in it (%s/%s), newer than this machine's" %
                                    (path, paths.META_DIR, FILE_NAME))
        except (HttpError, OSError, drivecache.DriveCacheError) as error:
            messages.print_line("Couldn't read the file list kept in %s: %s" % (path, error), 'red')
        uploader = Uploader(folder_path)
        uploader.start()
        uploaders.append((path, uploader))
    try:
        yield
    finally:
        for path, uploader in uploaders:
            if not dryrun.DRYRUN and uploader.is_changed():
                messages.print_line("Keeping %s's file list in it (%s/%s)..." % (path, paths.META_DIR, FILE_NAME))
            try:
                uploader.stop()
            except (HttpError, OSError) as error:
                messages.show("Couldn't keep the file list in %s" % (path,),
                              ["Uploading it to %s/%s failed: %s" % (paths.META_DIR, FILE_NAME, error),
                               "It's uploaded at the next sync of it."], dryrun.label(), 'red')
