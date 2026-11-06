"""What a job knows of its files, and who it tells as they're hashed"""
from dirdelta.hashes.hashing.states import ALGORITHM


class JobFiles(object):
    """Its files (Job's)"""

    def hash_of(self, relpath):
        """The file's hash, if it's hashed (as of the scan), else None"""
        return self._hashes.get(relpath)

    def size_of(self, relpath):
        """The file's size (as of the scan), or None if it's not one of its files"""
        stamp = self._files.get(relpath)
        return stamp[0] if stamp is not None else None

    def is_being_hashed(self, relpath):
        return relpath in self._current

    def files(self):
        """The relpaths of its files (as of the scan), each dir's together, sorted"""
        with self._lock:
            return sorted(self._files, key=lambda relpath: relpath.split('/'))

    def failed(self):
        with self._lock:
            return set(self._failed)

    def is_failed(self, relpath):
        """Whether the file at relpath couldn't be hashed (since the last scan)"""
        with self._lock:
            return relpath in self._failed

    def hashes(self):
        """{relpath: {algorithm: hash}} of the files hashed"""
        with self._lock:
            return {relpath: {ALGORITHM: value} for relpath, value in self._hashes.items()}

    def unsubscribe(self, subscriber):
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def subscribe(self, subscriber):
        """Call subscriber(relpath, {algorithm: hash}) as each file is hashed (from the workers'
        threads, or a scan's), from now on. Returns {relpath: {algorithm: hash}} of the ones hashed
        before."""
        with self._lock:
            self._subscribers.append(subscriber)
            return {relpath: {ALGORITHM: value} for relpath, value in self._hashes.items()}
