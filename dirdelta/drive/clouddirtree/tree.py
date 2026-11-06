"""A tree of a Drive folder (CloudDirTree), read from the Drive cache; its changes are mixins,
each in a module of its own here"""
import collections
import os
import posixpath
import re

from googleapiclient.errors import HttpError

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import DUP_SUFFIX
from dirdelta.drive.clouddirtree.fetching import Fetching
from dirdelta.drive.clouddirtree.folders import Folders
from dirdelta.drive.clouddirtree.info import FileInfo, NO_INFO
from dirdelta.drive.clouddirtree.moves import Moves
from dirdelta.drive.clouddirtree.refresh import refresh_cache
from dirdelta.drive.clouddirtree.removals import Removals
from dirdelta.drive.clouddirtree.uploads import Uploads
from dirdelta.drive.clouddirtree.whole_folders import WholeFolders
from dirdelta.trees import dirtree
from dirdelta.trees import entries
from dirdelta.trees import paths


def factory(rootpath):
    """The tree of the cloud path rootpath (e.g. cloud/mein), from the Drive file list cache, which
    must exist (clouddirtreefactory makes sure it does)."""
    tree = CloudDirTree(rootpath)
    tree.update_from_cache()
    return tree


# What's known of a Drive file, from its metadata: its size in bytes (None for a Google file), a


class CloudDirTree(Fetching, Uploads, Folders, Moves, Removals, WholeFolders, dirtree.DirTree):

    """A dir tree representing a directory on the cloud (Google Drive). Files are copied into it by
    uploading them, out of it by downloading them, and removed from it to Drive's trash: a folder all
    of whose files are removed, as one.

    Google's own files (Docs, Sheets, ...) are in it too, by their names and an extension (see
    drivecache.path_name()). They can be removed, but not copied out: they're not files to
    download."""
    REMOVED_TO = " (to Drive's trash)"

    def __init__(self, rootpath):
        super(CloudDirTree, self).__init__(rootpath=paths.path_in_cloud(rootpath))
        self._forget_all()

    def _forget_all(self):
        # Each file's and folder's Drive id, by its relpath (the root's is '')
        self._cloud_ids = {}
        # What's known of each file, from Drive's metadata (a FileInfo), by its relpath
        self._infos = {}

    def _info(self, relpath):
        return self._infos.get(relpath, NO_INFO)

    def _rekey(self, relpath, new_relpath):
        """What's kept of the file or folder at relpath is new_relpath's now (it was moved)"""
        if relpath in self._cloud_ids:
            self._cloud_ids[new_relpath] = self._cloud_ids.pop(relpath)
        if relpath in self._infos:
            self._infos[new_relpath] = self._infos.pop(relpath)

    def displayname(self):
        """The cloud path, as given (cloud/mein), rather than the path in Drive (/mein), which
        reads like a local dir"""
        return paths.join_cloud(self.fullpath())

    def update_from_cache(self, found=None):
        """Add the files and folders in the Drive file list cache (drivecache) under the tree's root
        (or found: drivecache.entries() of it, already read)"""
        if found is None:
            found = drivecache.entries(self.fullpath())
        for relpath, cloud_id, is_dir, is_google_file, size, date_taken, hashes, modified in found:
            if relpath == '':
                self._cloud_ids[relpath] = cloud_id
                continue
            # Change node ID if it already exists (two files with the same path is possible in cloud)
            if relpath in self:
                relpath += DUP_SUFFIX + cloud_id
            if is_dir:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
            else:
                self.add_file_by_relpath(relpath)
                self._infos[relpath] = FileInfo(size, date_taken, hashes or {}, modified, is_google_file)
            self._cloud_ids[relpath] = cloud_id

    def _cache_add(self, md, relpath=None):
        """Add what dirdelta made or changed in Drive (its metadata) to the cache, noting that the
        cache has the tree as Drive has it now (drivecache.note_updated()), unless it's in
        paths.META_DIR: what dirdelta keeps there isn't the tree's files"""
        drivecache.add(md)
        if relpath is None or not paths.is_meta(relpath):
            drivecache.note_updated(self.fullpath())

    def reload_from_cache(self):
        """Rebuild the tree from the cache (e.g. after what's under it was replaced there). Raises
        DriveCacheError if what's there can't be a tree; then the tree is as it was."""
        # Read before the tree is emptied, so it's kept if they can't be a tree
        found = list(drivecache.entries(self.fullpath()))
        listeners = self._listeners
        super(CloudDirTree, self).__init__(rootpath=self.fullpath())
        self._listeners = listeners
        self._forget_all()
        self.update_from_cache(found)

    def refresh_from_drive(self, relpath=''):
        """Read the folder at relpath (default: the tree's root) anew from Drive, into the cache
        (refresh_cache()), and rebuild the tree from it. A relpath the tree has no folder at (e.g.
        a dir only the other replica has) refreshes the closest folder above it that it has.
        Returns the relpath refreshed. Raises as refresh_cache() does, or DriveCacheError if what's
        there can't be a tree; either way (and on Ctrl-C), the tree is as it was."""
        while relpath and not isinstance(getattr(self.get_node(relpath), 'data', None), entries.DirEntry):
            relpath = os.path.dirname(relpath)
        refresh_cache(posixpath.join(self.fullpath(), relpath))
        self.reload_from_cache()
        return relpath

    def file_size(self, relpath):
        return self._info(relpath).size

    def date_taken(self, relpath):
        return self._info(relpath).date_taken

    def content_hash(self, relpath, algorithm, should_stop=None):
        # Drive's, so nothing's read
        return self._info(relpath).hashes.get(algorithm)

    def known_hash(self, relpath, algorithm):
        return self._info(relpath).hashes.get(algorithm)

    def known_hashes(self, relpath):
        return tuple(self._info(relpath).hashes)

    def modified_time(self, relpath):
        return self._info(relpath).modified

    def files_by_name(self, progress=None):
        # A same-named file's relpath has a DUP_SUFFIX, its name doesn't
        found = collections.defaultdict(list)
        for name, files in super(CloudDirTree, self).files_by_name(progress).items():
            found[name.split(DUP_SUFFIX)[0]] += files
        return found

    def thumbnail(self, relpath, size):
        """Drive's thumbnail of the file at relpath (an image file's contents, at most size pixels
        on a side), or None if it has none (e.g. a file Drive makes none of), or it can't be got"""
        cloud_id = self._cloud_ids.get(relpath)
        if cloud_id is None:
            return None
        try:
            link = driveapi.service().files().get(fileId=cloud_id, fields='thumbnailLink').execute(
                num_retries=2).get('thumbnailLink')
            if not link:
                return None
            # The link asks for a size (=s220, the default) at its end
            link = re.sub(r'=s\d+$', '', link) + '=s%d' % (size,)
            return driveapi.get_url(link)
        except (HttpError, OSError):
            return None
