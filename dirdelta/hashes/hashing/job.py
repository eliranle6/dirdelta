"""A local replica's hashing job (Job): its files hashed in the background, by the pool's threads"""
import collections
import os
import threading
import time

from dirdelta.hashes import hashcache
from dirdelta.hashes.hashing.job_files import JobFiles
from dirdelta.hashes.hashing.job_scanning import JobScanning
from dirdelta.hashes.hashing.pool import _pool, is_rotational
from dirdelta.hashes.hashing.reading import _Paused, _hash_file
from dirdelta.hashes.hashing.states import (ALGORITHM,
    DONE,
    HASHING,
    NOT_SCANNED,
    Progress,
    RATE_WINDOW,
    SCANNED,
    SCANNING)


class Job(JobScanning, JobFiles):


    """Hashing a local replica's files (see the module's doc)"""

    def __init__(self, root, max_depth=None):
        self.root = os.path.realpath(root)
        self.max_depth = max_depth
        self.max_workers = 1 if is_rotational(self.root) else None
        self._lock = threading.Lock()
        # Whether it was scanned, is being scanned, is hashing (started), and ever was
        self._is_scanned = False
        self._is_scanning = False
        # Whether another scan was asked for during one, and what it's to take (see scan())
        self._scan_again = False
        self._listed_again = None
        self._is_started = False
        self._was_started = False
        # {relpath: (size, mtime_ns)} of its files, as of the scan, and {relpath: hash} of the ones
        # hashed; the ones left (find's order: a dir's files together), and the ones to hash first
        self._files = {}
        self._hashes = {}
        self._left = collections.deque()
        self._first = collections.deque()
        # The ones that couldn't be hashed (unreadable, or changing while read), and the ones being
        # hashed now
        self._failed = set()
        self._current = set()
        self._size_done = 0
        # (time, bytes hashed) as the files are, for the rate
        self._samples = collections.deque()
        self._subscribers = []
        self._nr_workers = 0
        self.error = None

    def name(self):
        """The replica's name for the screens: its dir's name"""
        return os.path.basename(self.root) or self.root


    def start(self):
        """Hash the files left, in the background (resuming, if paused)"""
        with self._lock:
            self._is_started = self._was_started = True
        _pool().add(self)

    def pause(self):
        """Stop hashing (the files being hashed stop where they are), until start()"""
        with self._lock:
            self._is_started = False

    def is_started(self):
        return self._is_started

    def first(self, relpaths):
        """Hash the files at relpaths before the others (e.g. the ones a picker shows)"""
        with self._lock:
            self._first.extend(relpath for relpath in relpaths
                               if relpath in self._files and relpath not in self._hashes)

    def _next(self):
        """The next file to hash, taken off what's left, or None"""
        with self._lock:
            if not self._is_started:
                return None
            if self.max_workers is not None and self._nr_workers >= self.max_workers:
                return None
            for queue in (self._first, self._left):
                while queue:
                    relpath = queue.popleft()
                    if relpath in self._files and relpath not in self._hashes and relpath not in self._current:
                        self._current.add(relpath)
                        self._nr_workers += 1
                        return relpath
            return None

    def _take(self, relpath):
        """Take the file at relpath to hash it now (as _next() does), if it isn't hashed or being
        hashed. Returns whether it was taken."""
        with self._lock:
            if relpath not in self._files or relpath in self._hashes or relpath in self._current:
                return False
            self._current.add(relpath)
            self._nr_workers += 1
            return True

    def _hash(self, relpath):
        """Hash the file (a worker's), unless it's paused meanwhile (then it's left for later)"""
        path = os.path.join(self.root, relpath)
        value, stamp = None, None
        try:
            value = hashcache.get(path, ALGORITHM)
            if value is None:
                value, stamp = _hash_file(path, lambda: not self._is_started)
        except _Paused:
            with self._lock:
                self._current.discard(relpath)
                self._nr_workers -= 1
                self._first.appendleft(relpath)
            return
        if value is not None and stamp is not None:
            hashcache.put(path, {ALGORITHM: value}, stamp)
        with self._lock:
            self._current.discard(relpath)
            self._nr_workers -= 1
            size = self._files.get(relpath, (0, 0))[0]
            if value is None:
                self._failed.add(relpath)
            else:
                self._hashes[relpath] = value
            self._size_done += size
            now = time.monotonic()
            self._samples.append((now, size))
            while self._samples and self._samples[0][0] < now - RATE_WINDOW:
                self._samples.popleft()
            subscribers = list(self._subscribers) if value is not None else []
        for subscriber in subscribers:
            subscriber(relpath, {ALGORITHM: value})

    def _state(self):
        """Its state (see NOT_SCANNED), with the lock held"""
        if not self._is_scanned:
            return SCANNING if self._is_scanning else NOT_SCANNED
        if not self._current and len(self._hashes) + len(self._failed) >= len(self._files):
            return DONE
        return HASHING if self._is_started else SCANNED

    # What it knows

    def progress(self):
        with self._lock:
            rate = None
            if len(self._samples) > 1:
                elapsed = self._samples[-1][0] - self._samples[0][0]
                if elapsed > 0:
                    rate = sum(size for _, size in list(self._samples)[1:]) / elapsed
            state = self._state()
            return Progress(state, len(self._files), len(self._hashes) + len(self._failed),
                            sum(size for size, _ in self._files.values()), self._size_done,
                            sorted(self._current), rate, len(self._failed),
                            self._was_started and not self._is_started and state == SCANNED,
                            self._is_started)
