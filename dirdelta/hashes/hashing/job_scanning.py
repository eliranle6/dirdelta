"""A job's scan: listing its replica's files, and telling which are hashed already"""
import collections
import threading

from dirdelta.hashes import hashcache
from dirdelta.hashes.hashing.pool import _pool
from dirdelta.hashes.hashing.reading import _list_files
from dirdelta.hashes.hashing.states import ALGORITHM
from dirdelta.trees import paths


class JobScanning(object):
    """Scanning (Job's)"""

    def scan(self, listed=None):
        """List its files (or take listed, {relpath: (size, mtime_ns)}, e.g. its tree's scan's),
        and tell which are hashed already (from the hash cache); the rest are left to hash. Again
        after its files changed (e.g. copied into it): the hashed ones are kept. One at a time, or an
        older scan finishing later would undo a newer one: while one's going, this only asks for one
        more after it (with the latest listed, if any), and returns."""
        with self._lock:
            if self._is_scanning:
                self._scan_again, self._listed_again = True, listed
                return
            self._is_scanning = True
        try:
            while True:
                self._scan_once(listed)
                with self._lock:
                    if not self._scan_again:
                        self._is_scanning = False
                        return
                    listed, self._listed_again = self._listed_again, None
                    self._scan_again = False
        except BaseException:
            with self._lock:
                self._is_scanning = self._scan_again = False
                self._listed_again = None
            raise

    def _scan_once(self, listed):
        try:
            if listed is None:
                listed = _list_files(self.root, self.max_depth)
        except OSError as error:
            with self._lock:
                self.error = str(error)
            return
        # What dirdelta keeps in the replica isn't its files (its hashes are in it, see hashcache.py)
        listed = {relpath: stamp for relpath, stamp in listed.items() if not paths.is_meta(relpath)}
        kept = hashcache.known_under(self.root)
        hashes, left, size_done = {}, [], 0
        for relpath, stamp in listed.items():
            known = kept.get(relpath)
            if known is not None and known[:2] == stamp and ALGORITHM in known[2]:
                hashes[relpath] = known[2][ALGORITHM]
                size_done += stamp[0]
            else:
                left.append(relpath)
        with self._lock:
            new = {relpath: value for relpath, value in hashes.items() if self._hashes.get(relpath) != value}
            self._files, self._hashes = listed, hashes
            # The ones that couldn't be hashed are tried again
            self._failed = set()
            self._left = collections.deque(left)
            self._first = collections.deque(relpath for relpath in self._first if relpath in listed)
            self._size_done = size_done
            self.error = None
            self._is_scanned = True
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            for relpath, value in new.items():
                subscriber(relpath, {ALGORITHM: value})
        if self._is_started:
            _pool().wake()

    def scan_in_background(self, listed=None):
        threading.Thread(target=self.scan, args=(listed,), daemon=True).start()
