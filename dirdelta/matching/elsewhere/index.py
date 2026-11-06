"""A replica's files by name, size and hash (Index), built once and kept up to date"""
import collections
import os
import threading

from dirdelta.matching.elsewhere.constants import RENAMED_MIN_SIZE
from dirdelta.matching.elsewhere.index_files import IndexFiles
from dirdelta.matching.elsewhere.index_hashes import IndexHashes
from dirdelta.trees import paths


class Index(IndexHashes, IndexFiles):


    """A replica's files by name (and the big ones by size), built once (in the background, by
    find_previews(), or by sure_matches()), and then kept up to date by the replica, which tells it
    of the files copied into it, removed from it or moved in it (add(), remove(), move(); see
    DirTree.add_listener()), rather than built again; or built again after the replica is read anew
    (invalidate()).

    Its files by their contents' hashes too, the ones known without reading the files: Drive's (once
    built), and a local replica's that its hashing job (hashing.py) has hashed, which come as they're
    hashed (built or not)."""

    def __init__(self, replica, excluded=None):
        """excluded: a dir (relpath) of the replica whose files aren't in it (e.g. an inbox in a
        sorted tree, whose files would be their own matches)"""
        self.replica = replica
        replica.add_listener(self)
        self._excluded = excluded
        # {name: {relpath: size}}, the names in each dir, and {size: relpaths} of the big ones
        # (RENAMED_MIN_SIZE), once built
        self._by_name = None
        self._names_by_dir = None
        self._by_size = None
        # {(algorithm, hash): relpaths} of the files whose hashes are known without reading them
        self._by_hash = collections.defaultdict(set)
        # Dates taken read so far, and contents' hashes ({algorithm: hex}), by relpath
        self._dates_taken = {}
        self._hashes = {}
        # A local replica's hashing job, once there's one, and what it hashed that isn't in yet
        # (it's sent from its threads); and the relpaths whose hashes came since take_new()
        self._job = None
        # Around what changes its maps, and what reads them on other threads (a replica's changes
        # come on the thread making them, its previews are worked out on another); and one build at
        # a time, with the changes that come meanwhile, to apply to what it found
        self._lock = threading.RLock()
        self._build_lock = threading.Lock()
        self._is_building = False
        self._changes_meanwhile = []
        # How many times it was invalidated: a build begun before the last isn't of what's there
        self._nr_invalidated = 0
        # How many files were removed (or moved) so far: what's read of one meanwhile may be another's
        self._nr_removed = 0
        self._pending = []
        self._new = set()
        # How many files it has (once built), and the ones with a hash known, by algorithm
        self._nr_files = 0
        self._hashed = collections.defaultdict(set)

    def is_built(self):
        return self._by_name is not None

    def build(self, progress=None):
        """Build it, unless it is: from the replica's files_by_name(progress), which may raise to
        stop it (and then it isn't built). What changes in the replica meanwhile goes in it too, and
        if it's invalidated meanwhile, it's built anew. Another thread's build is waited for."""
        if self.is_built():
            return
        with self._build_lock:
            if self.is_built():
                return
            with self._lock:
                self._is_building = True
                self._changes_meanwhile = []
            try:
                while not self._built_from_a_listing(progress):
                    pass
            finally:
                with self._lock:
                    self._is_building = False
                    self._changes_meanwhile = []

    def _built_from_a_listing(self, progress):
        """List the replica's files, and make what's listed the index, unless it was invalidated
        meanwhile. Returns whether it was made."""
        with self._lock:
            nr_invalidated = self._nr_invalidated
        by_name = {}
        for name, files in self.replica.files_by_name(progress).items():
            files = {relpath: size for relpath, size in files if not self._is_excluded(relpath)}
            if files:
                by_name[name] = files
        names_by_dir = collections.defaultdict(set)
        by_size = collections.defaultdict(set)
        known = {}
        for name, files in by_name.items():
            for relpath, size in files.items():
                names_by_dir[os.path.dirname(relpath)].add(name)
                if size is not None and size >= RENAMED_MIN_SIZE:
                    by_size[size].add(relpath)
                for algorithm in self.replica.known_hashes(relpath):
                    known.setdefault(relpath, {})[algorithm] = self.replica.content_hash(relpath, algorithm)
        with self._lock:
            if nr_invalidated != self._nr_invalidated:
                self._changes_meanwhile = []
                return False
            for relpath, hashes in known.items():
                self._add_hashes(relpath, hashes)
            self._names_by_dir, self._by_size = names_by_dir, by_size
            self._nr_files = sum(len(files) for files in by_name.values())
            # Last: is_built() says it is once all is
            self._by_name = by_name
            self._is_building = False
            # What the listing may or may not have seen
            for change, args in self._changes_meanwhile:
                change(*args)
            self._changes_meanwhile = []
        return True

    def _is_excluded(self, relpath):
        return self._excluded is not None and paths.is_at_or_under(relpath, self._excluded)

    def invalidate(self):
        with self._lock:
            self._nr_invalidated += 1
            self._nr_removed += 1
            self._by_name = self._names_by_dir = self._by_size = None
            self._by_hash = collections.defaultdict(set)
            self._hashed = collections.defaultdict(set)
            self._dates_taken = {}
            self._hashes = {}
            self._pending = []
            # Its job's hashes are still known
            if self._job is not None:
                for relpath, hashes in self._job.hashes().items():
                    self._add_hashes(relpath, hashes)
