"""What's been read from a source (Pool), one for each source (a phone's DCIM, or any dir), shared by
the imports from it whatever replica they go into: each file's size and time as listed, its SHA-1 once
it's been copied (and so hashed), and the copies (files/) and thumbnails (thumbs/), so nothing is read
from a phone, or kept, twice. Kept under IMPORTS_DIR/sources/, by the source's path."""
import hashlib
import json
import os
import shutil
import threading

from dirdelta.phoneimport import store
from dirdelta.trees import paths

SOURCES_DIR = 'sources'
MANIFEST = 'pool.json'
FILES_DIR = 'files'
THUMBS_DIR = 'thumbs'

# {source: its Pool}, so the imports of a source share one (and its lock)
_pools = {}
_lock = threading.Lock()


class Pool(object):
    """The files of source: {relpath: {'size', 'mtime', 'sha1' (or None), 'copied' (whether its copy is
    here)}}"""

    def __init__(self, source, files=None):
        self.source = source
        self.files = files or {}
        self.lock = threading.RLock()
        self._tree = None

    @property
    def folder(self):
        return os.path.join(store.IMPORTS_DIR, SOURCES_DIR, hashlib.sha1(self.source.encode()).hexdigest()[:16])

    def local_path(self, relpath):
        """Where the file at relpath is copied to"""
        return os.path.join(self.folder, FILES_DIR, relpath)

    def thumb_path(self, relpath):
        return os.path.join(self.folder, THUMBS_DIR, relpath + '.jpg')

    def readable_path(self, relpath):
        """The file at relpath: its copy, or else the source's (read from the phone), or None (a Drive
        file not downloaded)"""
        with self.lock:
            info = self.files.get(relpath)
        if info is None or (self.is_drive and not info['copied']):
            return None
        return self.local_path(relpath) if info['copied'] else os.path.join(self.source, relpath)

    @property
    def is_drive(self):
        return paths.is_cloud_path(self.source)

    def tree(self):
        """A Drive source's tree (from the Drive cache, read once), for its thumbnails and downloads"""
        with self.lock:
            if self._tree is None:
                from dirdelta.drive.clouddirtree import tree
                self._tree = tree.factory(self.source)
            return self._tree

    def add(self, listed, is_whole=False):
        """The files listed ({relpath: (size, mtime) or (size, mtime, sha1): a Drive source's know
        theirs}) as they are now: a new one added, a changed one read again (its copy and hash
        dropped); the ones not listed are kept (a copy may be needed), unless is_whole (a Drive
        folder's list: what's not in it was moved or removed) and they aren't copied"""
        with self.lock:
            for relpath, listing in listed.items():
                size, mtime, sha1 = (tuple(listing) + (None,))[:3]
                found = self.files.get(relpath)
                if found is not None and (found['size'], found['mtime']) == (size, mtime):
                    continue
                if found is not None and found['copied']:
                    _remove(self.local_path(relpath))
                    _remove(self.thumb_path(relpath))
                self.files[relpath] = {'size': size, 'mtime': mtime, 'sha1': sha1, 'copied': False}
            if is_whole:
                for relpath in [relpath for relpath, info in self.files.items() if relpath not in listed and not info['copied']]:
                    del self.files[relpath]
            self._tree = None
            self.save()

    def copied(self, relpath, sha1):
        with self.lock:
            self.files[relpath].update(sha1=sha1, copied=True)

    def gone(self, relpath):
        """The copy of relpath is gone (moved into a replica); its hash is kept"""
        with self.lock:
            self.files[relpath]['copied'] = False

    def save(self):
        with self.lock:
            os.makedirs(self.folder, exist_ok=True)
            temp_path = os.path.join(self.folder, MANIFEST + '.tmp')
            with open(temp_path, 'w') as manifest:
                json.dump({'source': self.source, 'files': self.files}, manifest)
            os.replace(temp_path, os.path.join(self.folder, MANIFEST))

    def remove(self):
        """Remove what's kept of the source: its copies, thumbnails and hashes"""
        with _lock:
            _pools.pop(self.source, None)
        shutil.rmtree(self.folder, ignore_errors=True)


def of(source):
    """The Pool of source (read from its manifest, if it has one)"""
    with _lock:
        found = _pools.get(source)
        if found is None:
            found = _pools[source] = Pool(source)
            try:
                with open(os.path.join(found.folder, MANIFEST)) as manifest:
                    found.files = json.load(manifest).get('files', {})
            except (OSError, ValueError):
                pass
        return found


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
