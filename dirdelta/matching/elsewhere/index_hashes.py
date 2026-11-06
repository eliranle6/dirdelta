"""What an Index knows of its files' hashes, without reading them, and what it reads"""
from dirdelta.hashes import hashing
from dirdelta.trees import localdiskdirtree


class IndexHashes(object):
    """An Index's hashes"""

    # The hashes known without reading the files

    def _take_hashes(self):
        """Take in what its hashing job hashed since (subscribing to it, once there's one)"""
        if self._job is None and localdiskdirtree.is_local(self.replica):
            job = hashing.job_for(self.replica.fullpath())
            if job is not None:
                with self._lock:
                    if self._job is None:
                        self._job = job
                        for relpath, hashes in job.subscribe(self._on_hashed).items():
                            self._add_hashes(relpath, hashes)
        if self._pending:
            with self._lock:
                pending, self._pending = self._pending, []
                for relpath, hashes in pending:
                    self._add_hashes(relpath, hashes)

    def _on_hashed(self, relpath, hashes):
        """Its job hashed a file (on the job's thread)"""
        with self._lock:
            self._pending.append((relpath, hashes))

    def _add_hashes(self, relpath, hashes):
        """With the lock held"""
        if self._is_excluded(relpath):
            return
        known = self._hashes.setdefault(relpath, {})
        for algorithm, value in hashes.items():
            if value is None:
                continue
            if known.get(algorithm) not in (None, value):
                self._by_hash.get((algorithm, known[algorithm]), set()).discard(relpath)
            self._hashed[algorithm].add(relpath)
            known[algorithm] = value
            self._by_hash[algorithm, value].add(relpath)
        self._new.add(relpath)

    def job(self):
        """Its replica's hashing job, if it's local and has one, else None"""
        self._take_hashes()
        return self._job

    def known(self, relpath):
        """{algorithm: hash} of the file's contents known without reading it"""
        self._take_hashes()
        with self._lock:
            found = self._hashes.setdefault(relpath, {})
            for algorithm in self.replica.known_hashes(relpath):
                if algorithm not in found:
                    # Kept, as content_hashes() keeps what it works out
                    found[algorithm] = self.replica.content_hash(relpath, algorithm)
            return {algorithm: value for algorithm, value in found.items() if value is not None}

    def hash_coverage(self, algorithm):
        """How much of its files (0 to 1) have their hashes by algorithm known (without reading
        them), or None if it isn't built"""
        if not self.is_built():
            return None
        self._take_hashes()
        with self._lock:
            return min(1, len(self._hashed[algorithm]) / self._nr_files) if self._nr_files else 1

    def take_new(self):
        """The relpaths of the files whose hashes came (or were worked out) since it was last called"""
        self._take_hashes()
        with self._lock:
            new, self._new = self._new, set()
        return new

    def content_hash(self, relpath, algorithm, should_stop=None):
        """The file's contents' hash, as the replica's content_hash() gives it (worked out once)"""
        return self.content_hashes(relpath, [algorithm], should_stop)[algorithm]

    def content_hashes(self, relpath, algorithms, should_stop=None):
        """{algorithm: hash} of the file's contents, the ones not worked out yet in one read (without
        the lock: it may read a big file), kept unless the file was moved or removed meanwhile"""
        with self._lock:
            hashes = self._hashes.setdefault(relpath, {})
            found = {algorithm: hashes[algorithm] for algorithm in algorithms if algorithm in hashes}
        needed = [algorithm for algorithm in algorithms if algorithm not in found]
        if needed:
            read = self.replica.content_hashes(relpath, needed, should_stop)
            found.update(read)
            with self._lock:
                if self._hashes.get(relpath) is hashes:
                    hashes.update(read)
        return {algorithm: found[algorithm] for algorithm in algorithms}
