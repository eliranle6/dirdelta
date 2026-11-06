"""Copying files into a Drive tree: uploading them, a few at once"""
import concurrent.futures
import os

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import NUM_RETRIES, RESUMABLE_MIN_SIZE, UPLOAD_THREADS
from dirdelta.drive.clouddirtree.info import info_of
from dirdelta.trees import entries
from dirdelta.ui import messages


class Uploads(object):
    """Uploads (CloudDirTree's)"""

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

    def _upload_files(self, files, starting, copied, changes):
        """_copy_files()'s uploads, into the folders made (changes: drivecache.changing()'s)"""
        not_started = iter(files)
        under_way = {}
        executor = concurrent.futures.ThreadPoolExecutor(UPLOAD_THREADS)
        try:
            try:
                while True:
                    for file_entry in not_started:
                        starting(file_entry)
                        try:
                            parent_id = self._folder_id(os.path.dirname(file_entry.relpath))
                        except HttpError as error:
                            messages.print_line("Copy failed: %s" % (error,), "red")
                            copied(False)
                            continue
                        # Inside replacing(), the file there gets it as its new version
                        replaced_id = (self._cloud_ids.get(file_entry.relpath)
                                       if self._is_replacing and self.has_file(file_entry.relpath) else None)
                        under_way[executor.submit(self._upload, file_entry, parent_id, replaced_id)] = file_entry
                        if len(under_way) == UPLOAD_THREADS:
                            break
                    if not under_way:
                        break
                    done, _ = concurrent.futures.wait(
                        under_way, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        # Dropped once it's in the cache, so a Ctrl-C in the middle still waits for it
                        copied(self._uploaded(under_way[future], future))
                        del under_way[future]
            except KeyboardInterrupt:
                if under_way:
                    messages.print_line("Waiting for the %d uploads under way..." % (len(under_way),))
                    for future in concurrent.futures.as_completed(under_way):
                        copied(self._uploaded(under_way[future], future))
                # All that was started is in the cache
                changes.settled = True
                raise
        finally:
            executor.shutdown(wait=False)

    def _copy_file(self, file_entry, source):
        """Upload file_entry, as _copy_files() does"""
        results = []
        self._copy_files([file_entry], source, lambda _: None, results.append)
        return results[0]

    def _upload(self, file_entry, parent_id, replaced_id=None):
        """Upload file_entry into the folder with parent_id, on any thread: a new file, or with
        replaced_id, a new version of that one (Drive keeps the old one among its versions). Returns
        what Drive says of the file (its id, ...), with what it was made with. Raises HttpError or
        OSError if it can't."""
        path = file_entry.full_filesystem_path()
        media = MediaFileUpload(path, resumable=os.path.getsize(path) >= RESUMABLE_MIN_SIZE)
        # When it was modified, as on the disk, rather than when it was uploaded
        body = {'name': os.path.basename(file_entry.relpath), 'parents': [parent_id],
                'modifiedTime': drivecache.rfc3339(os.path.getmtime(path))}
        if replaced_id is not None:
            updated = driveapi.service().files().update(
                fileId=replaced_id, body={'modifiedTime': body['modifiedTime']}, media_body=media,
                fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
            return dict(body, **updated)
        created = driveapi.service().files().create(
            body=body, media_body=media, fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
        return dict(body, **created)

    def write_file(self, relpath, local_path):
        """Make the file at relpath (in a folder the tree has) the local file's contents: a new
        version of it, if it's there (keeping its id), else a new file; and note it in the cache.
        Raises HttpError or OSError if it can't."""
        with drivecache.changing(self.fullpath()):
            parent_id = self._cloud_ids[os.path.dirname(relpath)]
            if self.has_file(relpath):
                md = driveapi.service().files().update(
                    fileId=self._cloud_ids[relpath], media_body=MediaFileUpload(local_path),
                    fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
                md = dict(md, parents=[parent_id])
            else:
                md = self._upload(entries.FileEntry(os.path.basename(relpath), relpath, local_path), parent_id)
                self.add_file_by_relpath(relpath)
            self._cache_add(md, relpath)
        self._cloud_ids[relpath] = md['id']
        self._infos[relpath] = info_of(md)

    def _uploaded(self, file_entry, future):
        """Add file_entry, whose upload (future, of _upload()) ended, to the tree and the cache.
        Returns whether it was uploaded."""
        try:
            md = future.result()
        except (HttpError, OSError) as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        self._cache_add(md)
        if self.has_file(file_entry.relpath):
            # Replaced (see replacing()): what listens drops what it knew of the old version
            self._tell_removed(file_entry.relpath)
        self.add_file_by_relpath(file_entry.relpath)
        self._cloud_ids[file_entry.relpath] = md['id']
        self._infos[file_entry.relpath] = info_of(md)
        self._tell_added(file_entry.relpath)
        return True
