"""Whether replicas have a file already (Known): by its contents (its SHA-1: a local replica's from the
hash cache, where the file hasn't changed since it was hashed, a Drive one's from the Drive cache), or
else by its name and size, wherever it is in them"""
import collections
import os
import posixpath
import threading

from dirdelta.drive import drivecache
from dirdelta.hashes import hashcache
from dirdelta.trees import localscan
from dirdelta.trees import paths

# How it was found: the same contents, or a file of the same name and size
SAME_CONTENTS, SAME_NAME_AND_SIZE = 'same contents', 'same name and size'


class Known(object):
    """What the replicas at replica_paths have, indexed once (index(), on the first ask)"""

    def __init__(self, replica_paths):
        self.replica_paths = list(replica_paths)
        self._by_sha1 = collections.defaultdict(list)
        self._by_name_size = collections.defaultdict(list)
        # {replica path: [the relpaths of its dirs]}
        self.dirs = {}
        self.errors = []
        self._lock = threading.Lock()
        self._is_indexed = False

    def index(self):
        with self._lock:
            if self._is_indexed:
                return
            for replica_path in self.replica_paths:
                try:
                    if paths.is_cloud_path(replica_path):
                        self._index_drive(replica_path)
                    else:
                        self._index_local(replica_path)
                except (OSError, drivecache.DriveCacheError) as error:
                    self.errors.append("%s: %s" % (replica_path, error))
            self._is_indexed = True

    def _index_local(self, root):
        if not os.path.isdir(root):
            raise OSError("not there (not mounted?)")
        scan = localscan.scan(root)
        real_root = os.path.realpath(root)
        if os.path.exists(hashcache.replica_file(real_root)):
            # Its hashes are kept in it (as a sync's start reads them)
            hashcache.use_replica(real_root)
        hashed = hashcache.known_under(real_root)
        self.dirs[root] = sorted(relpath for relpath, (kind, _, _) in scan.entries.items() if kind == localscan.DIR)
        for relpath, (size, mtime_ns) in scan.files().items():
            stamp_size, stamp_mtime, hashes = hashed.get(relpath, (None, None, {}))
            sha1 = hashes.get('sha1') if (stamp_size, stamp_mtime) == (size, mtime_ns) else None
            self._add(root, relpath, size, sha1)

    def _index_drive(self, replica_path):
        dirs = []
        for entry in drivecache.entries(paths.path_in_cloud(replica_path)):
            if entry.is_dir:
                if entry.relpath:
                    dirs.append(entry.relpath)
                continue
            sha1 = entry.hashes.get('sha1')
            if entry.size is not None:
                self._add(replica_path, entry.relpath, entry.size, sha1)
            elif sha1:
                self._by_sha1[sha1].append((replica_path, entry.relpath))
        self.dirs[replica_path] = sorted(dirs)

    def _add(self, root, relpath, size, sha1=None):
        self._by_name_size[(posixpath.basename(relpath).lower(), size)].append((root, relpath, sha1))
        if sha1:
            self._by_sha1[sha1].append((root, relpath))

    def found(self, name, size, sha1=None):
        """[(replica path, relpath, how)] of where the replicas have the file (each replica once: by
        its contents if it can tell, else by its name and size, unless both hashes are known and differ)"""
        self.index()
        found, seen = [], set()
        for root, relpath in self._by_sha1.get(sha1, []) if sha1 else []:
            if root not in seen:
                found.append((root, relpath, SAME_CONTENTS))
                seen.add(root)
        for root, relpath, their_sha1 in self._by_name_size.get((os.path.basename(name).lower(), size), []):
            if root not in seen and not (sha1 and their_sha1 and sha1 != their_sha1):
                found.append((root, relpath, SAME_NAME_AND_SIZE))
                seen.add(root)
        return found

    def media_relpaths(self, root):
        """The relpaths of the files of the local replica at root, as indexed (for the suggestions)"""
        self.index()
        return [relpath for (name, size), places in self._by_name_size.items() for replica, relpath, _ in places
                if replica == root]
