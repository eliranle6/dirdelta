"""Removing files from a Drive tree, to Drive's trash"""
from googleapiclient.errors import HttpError

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import MAX_LISTED, NUM_RETRIES
from dirdelta.drive.clouddirtree.refresh import _is_under, _listed
from dirdelta.ui import messages
from dirdelta.util import dryrun


class Removals(object):
    """Removals (CloudDirTree's)"""

    def removal_notes(self, relpaths):
        lines = []
        folders = self._whole_folders(set(relpaths))
        if folders:
            lines.append("Trashing %d folders whole, all of whose files are picked (checked with "
                         "Drive first, for files the cache doesn't have):" % (len(folders),))
            lines += _listed(folder + '/' for folder in folders)
        google_files = [relpath for relpath in relpaths if self._info(relpath).is_google]
        if google_files:
            lines.append("Including %d Google files (Docs, Sheets, ...), which are only in Drive:" %
                         (len(google_files),))
            lines += _listed(google_files)
        return lines

    def _remove_files(self, file_entries, starting, removed):
        """Move the files to Drive's trash: the topmost folders all of whose files are picked (see
        _whole_folders()) each as one, once Drive says it has nothing more in them than the tree
        does (it may, if the cache is out of date), and the other files one by one. Trashed as one,
        a folder is restored as one, and leaves no empty folders behind."""
        picked = {file_entry.relpath for file_entry in file_entries}
        # A kept folder, or one it's in, is never trashed whole (see keep_dirs())
        kept = {folder for folder in self._cloud_ids if folder and self._is_kept(folder)}
        folders = self._whole_folders(picked, kept)
        if folders and not dryrun.DRYRUN:
            holding_more = self._folders_holding_more(folders)
            if holding_more is None:
                folders = []
            elif holding_more:
                messages.print_line(
                    "Drive has files in %d folders that the cache doesn't (it's out of date), so "
                    "they're kept, and their picked files are removed one by one: %s" %
                    (len(holding_more), ', '.join(sorted(holding_more)[:MAX_LISTED])), "yellow")
                folders = self._whole_folders(picked, holding_more | kept)
        in_trashed_folders = set()
        for folder in folders:
            folder_files = [relpath for relpath in picked if _is_under(relpath, folder)]
            starting("folder %s/ and its %d files" % (folder, len(folder_files)), len(folder_files))
            if dryrun.DRYRUN or self._trash_folder(folder):
                removed(len(folder_files))
                in_trashed_folders.update(folder_files)
        for file_entry in file_entries:
            if file_entry.relpath not in in_trashed_folders:
                starting(file_entry)
                if dryrun.DRYRUN or self._remove_file(file_entry):
                    removed()

    def _trash_folder(self, relpath):
        """Move the folder at relpath, and all that's in it, to Drive's trash, and drop it from the
        tree. Returns whether it was moved."""
        if not self._trash(self._cloud_ids[relpath]):
            return False
        files = self.files_under(relpath)
        for node in self._tree.subtree(relpath).all_nodes_itr():
            self._forget(node.identifier)
        self.remove_node(relpath)
        for file_relpath in files:
            self._tell_removed(file_relpath)
        return True

    def _remove_file(self, file_entry):
        """Move file_entry to Drive's trash, where it can be restored from (for 30 days)"""
        if not self._trash(self._cloud_ids[file_entry.relpath]):
            return False
        self.remove_node(file_entry.relpath)
        self._forget(file_entry.relpath)
        self._tell_removed(file_entry.relpath)
        return True

    def _forget(self, relpath):
        """Drop what's kept of the file or folder at relpath, once it's gone: its id, and its size,
        hashes and times, so a later one of its path isn't taken for it"""
        self._cloud_ids.pop(relpath, None)
        self._infos.pop(relpath, None)

    def _trash(self, cloud_id):
        """Move the file or folder with cloud_id to Drive's trash (where it can be restored from, for
        30 days), and note it in the cache. Returns whether it was moved (if not, says why)."""
        # Stale until the change is in the cache, in case it's cut off in the middle
        try:
            with drivecache.changing(self.fullpath()):
                driveapi.service().files().update(fileId=cloud_id, body={'trashed': True}).execute(
                    num_retries=NUM_RETRIES)
                drivecache.trash(cloud_id)
                drivecache.note_updated(self.fullpath())
        except HttpError as error:
            messages.print_line("Remove failed: %s" % (error,), "red")
            return False
        return True
