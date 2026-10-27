import os

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from dirdelta import dirtree
from dirdelta import driveapi
from dirdelta import drivecache
from dirdelta import messages
from dirdelta import paths


def factory(rootpath):
    """The tree of the cloud path rootpath (e.g. cloud/mein), from the Drive file list cache, which
    must exist (clouddirtreefactory makes sure it does)."""
    tree = CloudDirTree(rootpath)
    tree.update_from_cache()
    return tree


class CloudDirTree(dirtree.DirTree):
    """A dir tree representing a directory on the cloud (Google Drive). Files are copied into it by
    uploading them, out of it by downloading them, and removed from it to Drive's trash."""
    REMOVED_TO = " (to Drive's trash)"

    def __init__(self, rootpath):
        super(CloudDirTree, self).__init__(rootpath=paths.path_in_cloud(rootpath))
        # Each file's and folder's Drive id, by its relpath (the root's is '')
        self._cloud_ids = {}

    def update_from_cache(self):
        """Add the files and folders in the Drive file list cache (drivecache) under the tree's root"""
        for relpath, cloud_id, is_dir in drivecache.entries(self.fullpath()):
            if relpath == '':
                self._cloud_ids[relpath] = cloud_id
                continue
            # Change node ID if it already exists (two files with the same path is possible in cloud)
            if relpath in self:
                relpath += f'___DUP__{cloud_id}'
            if is_dir:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
            else:
                self.add_file_by_relpath(relpath)
            self._cloud_ids[relpath] = cloud_id

    def fetch_file(self, relpath, local_path):
        """Download the file at relpath to local_path. Raises OSError if it can't."""
        try:
            request = driveapi.service().files().get_media(fileId=self._cloud_ids[relpath])
            with open(local_path, 'wb') as local_file:
                downloader = MediaIoBaseDownload(local_file, request)
                is_done = False
                while not is_done:
                    _, is_done = downloader.next_chunk()
        except HttpError as error:
            raise OSError("Download of %s failed: %s" % (relpath, error))

    def _copy_file(self, file_entry, source):
        """Upload file_entry (of a local dir: its full path is on the local disk) into the same
        relative path, making the folders it's in"""
        # Stale until the change is in the cache, in case it's cut off in the middle
        was_stale = drivecache.is_stale()
        drivecache.mark_stale()
        try:
            parent_id = self._folder_id(os.path.dirname(file_entry.relpath))
            media = MediaFileUpload(file_entry.full_filesystem_path(), resumable=True)
            body = {'name': os.path.basename(file_entry.relpath), 'parents': [parent_id]}
            created = driveapi.service().files().create(
                body=body, media_body=media, fields=drivecache.FILE_FIELDS).execute()
        except (HttpError, OSError) as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        drivecache.add(dict(body, **created))
        if not was_stale:
            drivecache.mark_fresh()
        self.add_file_by_relpath(file_entry.relpath)
        self._cloud_ids[file_entry.relpath] = created['id']
        return True

    def _folder_id(self, relpath):
        """The Drive id of the folder at relpath, making it (and the folders it's in) if needed"""
        if relpath not in self._cloud_ids:
            parent_id = self._folder_id(os.path.dirname(relpath))
            body = {'name': os.path.basename(relpath), 'mimeType': drivecache.FOLDER_MIME_TYPE,
                    'parents': [parent_id]}
            created = driveapi.service().files().create(
                body=body, fields=drivecache.FILE_FIELDS).execute()
            drivecache.add(dict(body, **created))
            self.create_dir_node_from_relpath_if_not_exists(relpath)
            self._cloud_ids[relpath] = created['id']
        return self._cloud_ids[relpath]

    def _remove_file(self, file_entry):
        """Move file_entry to Drive's trash, where it can be restored from (for 30 days)"""
        # Stale until the change is in the cache, in case it's cut off in the middle
        was_stale = drivecache.is_stale()
        drivecache.mark_stale()
        cloud_id = self._cloud_ids[file_entry.relpath]
        try:
            driveapi.service().files().update(fileId=cloud_id, body={'trashed': True}).execute()
        except HttpError as error:
            messages.print_line("Remove failed: %s" % (error,), "red")
            return False
        drivecache.trash(cloud_id)
        if not was_stale:
            drivecache.mark_fresh()
        self.remove_node(file_entry.relpath)
        del self._cloud_ids[file_entry.relpath]
        return True
