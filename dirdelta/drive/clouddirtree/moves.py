"""Moving and copying files within Drive: one request each, keeping the file's id"""
import os

from googleapiclient.errors import HttpError

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import DUP_SUFFIX, MAX_LISTED, NUM_RETRIES
from dirdelta.drive.clouddirtree.refresh import _changing_both
from dirdelta.ui import messages


class Moves(object):
    """Moves (CloudDirTree's)"""

    def cant_move(self, relpath):
        if self._info(relpath).is_google:
            return "a Google file, whose name in Drive has no extension"
        if DUP_SUFFIX in relpath:
            return "one of several files of the same name in its folder"
        return None

    def _handed_over(self, relpath, new_relpath, to):
        """What's kept of the file or folder at relpath is new_relpath's in to now (it was moved)"""
        if to is self:
            self._rekey(relpath, new_relpath)
            return
        if relpath in self._cloud_ids:
            to._cloud_ids[new_relpath] = self._cloud_ids[relpath]
        if relpath in self._infos:
            to._infos[new_relpath] = self._infos[relpath]
        self._forget(relpath)

    def _move_file(self, relpath, new_relpath, to=None):
        """Move the file in Drive (keeping its id, history and sharing): rename it, and put it in
        new_relpath's folder (in to, or this tree; made if needed) instead of its own; and note it in
        the cache"""
        to = to or self
        reason = self.cant_move(relpath)
        if reason is not None:
            messages.print_line("Skipped %s: %s" % (relpath, reason), "yellow")
            return False
        # Stale until the change is in the cache, in case it's cut off in the middle
        try:
            with _changing_both(self.fullpath(), to.fullpath()):
                parent_id = to._folder_id(os.path.dirname(new_relpath))
                old_parent_id = self._cloud_ids[os.path.dirname(relpath)]
                md = driveapi.service().files().update(
                    fileId=self._cloud_ids[relpath], body={'name': os.path.basename(new_relpath)},
                    addParents=parent_id, removeParents=old_parent_id,
                    fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
                # The file again, by its id: the cache's later line is the one it has
                self._cache_add(dict(md, parents=[parent_id]))
        except HttpError as error:
            messages.print_line("Move failed: %s" % (error,), "red")
            return False
        self.remove_node(relpath)
        to.add_file_by_relpath(new_relpath)
        self._handed_over(relpath, new_relpath, to)
        self._tell_moved(relpath, new_relpath, to)
        return True

    def _move_dir(self, dirpath, new_dirpath, to=None):
        """Move the folder in Drive, as one (keeping its id, and what's in it): rename it, and put it
        in new_dirpath's parent folder (in to, or this tree; made if needed) instead of its own; and
        note it in the cache"""
        to = to or self
        if dirpath not in self._cloud_ids:
            messages.print_line("Skipped %s/: Drive's id of it isn't known" % (dirpath,), "yellow")
            return False
        # Stale until the change is in the cache, in case it's cut off in the middle
        try:
            with _changing_both(self.fullpath(), to.fullpath()):
                parent_id = to._folder_id(os.path.dirname(new_dirpath))
                md = driveapi.service().files().update(
                    fileId=self._cloud_ids[dirpath], body={'name': os.path.basename(new_dirpath)},
                    addParents=parent_id, removeParents=self._cloud_ids[os.path.dirname(dirpath)],
                    fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
                self._cache_add(dict(md, parents=[parent_id], mimeType=drivecache.FOLDER_MIME_TYPE))
        except HttpError as error:
            messages.print_line("Move failed: %s" % (error,), "red")
            return False
        for relpath, new_relpath in self._move_subtree(dirpath, new_dirpath, to):
            self._handed_over(relpath, new_relpath, to)
            if to.has_file(new_relpath):
                self._tell_moved(relpath, new_relpath, to)
        return True

    def _copy_within(self, relpath, new_relpath, to=None):
        """Copy the file in Drive (one request: Drive copies it), into new_relpath's folder (in to, or
        this tree; made if needed), with its name; and note it in the cache"""
        to = to or self
        reason = self.cant_move(relpath)
        if reason is not None:
            messages.print_line("Skipped %s: %s" % (relpath, reason), "yellow")
            return False
        if new_relpath in to:
            messages.print_line("Skipped %s: %s is there already" % (relpath, new_relpath), "yellow")
            return False
        try:
            with _changing_both(self.fullpath(), to.fullpath()):
                parent_id = to._folder_id(os.path.dirname(new_relpath))
                body = {'name': os.path.basename(new_relpath), 'parents': [parent_id]}
                md = driveapi.service().files().copy(
                    fileId=self._cloud_ids[relpath], body=body,
                    fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
                md = dict(body, **md)
                self._cache_add(md)
        except HttpError as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        to.add_file_by_relpath(new_relpath)
        to._cloud_ids[new_relpath] = md['id']
        # The same contents (and so size, hashes, photo's date)
        if relpath in self._infos:
            to._infos[new_relpath] = self._infos[relpath]
        to._tell_added(new_relpath)
        return True

    def _moved(self, moves):
        """Trash the folders the moves left empty: the topmost of them, each as one, once Drive says
        it has nothing in them that the tree doesn't (see _folders_holding_more())"""
        emptied = set()
        for relpath, _ in moves:
            # The closest folder it was in that's still there (one moved whole isn't)
            folder = os.path.dirname(relpath)
            while folder and folder not in self:
                folder = os.path.dirname(folder)
            emptied.add(folder)
        emptied = {folder for folder in emptied
                   if folder and folder in self and not self.children(folder) and not self._is_kept(folder)}
        # And the folders that only those are in, up to the root
        while True:
            parents = {os.path.dirname(folder) for folder in emptied} - emptied - {''}
            more = {parent for parent in parents
                    if not self._is_kept(parent) and
                    all(node.identifier in emptied for node in self.children(parent))}
            if not more:
                break
            emptied |= more
        topmost = sorted(folder for folder in emptied if os.path.dirname(folder) not in emptied)
        if not topmost:
            return
        holding_more = self._folders_holding_more(topmost)
        if holding_more is None:
            return
        trashed = [folder for folder in topmost if folder not in holding_more and self._trash_folder(folder)]
        if trashed:
            messages.print_line("Moved %d folders left empty to Drive's trash: %s" %
                                (len(trashed), ', '.join(folder + '/' for folder in trashed[:MAX_LISTED])))
