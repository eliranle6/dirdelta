"""Copying a Drive tree's files out of it: downloading them"""
import os
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import PROGRESS_CHUNK_SIZE
from dirdelta.drive.clouddirtree.refresh import _listed


class Fetching(object):
    """Downloads (CloudDirTree's)"""

    def cant_fetch(self, relpath):
        if self._info(relpath).is_google:
            return "a Google file, which is only in Drive, so it can't be copied to a dir"
        return None

    def copy_notes(self, relpaths):
        google_files = [relpath for relpath in relpaths if self._info(relpath).is_google]
        if not google_files:
            return []
        return (["%s Google files (Docs, Sheets, ...), which are only in Drive, so they can't be "
                 "copied to a dir: skipped" % (len(google_files),)] + _listed(google_files))

    def fetch_file(self, relpath, local_path, progress=None):
        """Download the file at relpath to local_path. Raises OSError if it can't. With progress,
        it's called with how many bytes are downloaded so far, after each PROGRESS_CHUNK_SIZE (one
        request after another, never at once)."""
        reason = self.cant_fetch(relpath)
        if reason is not None:
            raise OSError("Can't download %s: %s" % (relpath, reason))
        try:
            request = driveapi.service().files().get_media(fileId=self._cloud_ids[relpath])
            with open(local_path, 'wb') as local_file:
                if progress is None:
                    downloader = MediaIoBaseDownload(local_file, request)
                else:
                    downloader = MediaIoBaseDownload(local_file, request, chunksize=PROGRESS_CHUNK_SIZE)
                is_done = False
                while not is_done:
                    status, is_done = downloader.next_chunk()
                    if progress is not None and status is not None:
                        progress(status.resumable_progress)
        except HttpError as error:
            raise OSError("Download of %s failed: %s" % (relpath, error))
        # When it was modified, as in Drive, rather than when it was downloaded
        modified = self.modified_time(relpath)
        if modified is not None:
            os.utime(local_path, (modified, modified))

    def _copy_files(self, files, source, starting, copied):
        """Upload files (of a local dir: their full paths are on the local disk) into the same
        relative paths: first the folders they're in that Drive lacks (_make_folders()), then
        UPLOAD_THREADS files at a time. What Drive says of each upload is added to the tree and the
        cache here, on this thread, as it ends. Ctrl-C starts no more, and waits for the ones under
        way, so the cache has them (and Ctrl-C again doesn't wait: they end on their own)."""
        # Stale until the changes are in the cache, in case it's cut off in the middle
        with drivecache.changing(self.fullpath()) as changes:
            self._make_folders(os.path.dirname(file_entry.relpath) for file_entry in files)
            self._upload_files(files, starting, copied, changes)
