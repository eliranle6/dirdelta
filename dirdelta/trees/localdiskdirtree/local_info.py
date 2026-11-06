"""What a local replica says of its files: sizes, dates, hashes"""
import collections
import hashlib
import os

from dirdelta.hashes import hashcache
from dirdelta.trees import dirtree
from dirdelta.trees import localscan
from dirdelta.util import exif


# How much of a file content_hash() reads at a time (asking should_stop() after each)
HASH_READ_SIZE = 1 << 20


class LocalInfo(object):
    """Its files' info (LocalReplica's)"""

    def file_size(self, relpath):
        try:
            return os.lstat(os.path.join(self._rootpath, relpath)).st_size
        except OSError:
            return None

    def date_taken(self, relpath):
        return exif.date_taken(os.path.join(self._rootpath, relpath))

    def modified_time(self, relpath):
        try:
            return os.lstat(os.path.join(self._rootpath, relpath)).st_mtime
        except OSError:
            return None

    def local_path(self, relpath):
        return os.path.join(self._rootpath, relpath)

    def known_hash(self, relpath, algorithm):
        return hashcache.get(os.path.join(self._rootpath, relpath), algorithm)

    def listed(self, algorithm):
        kept = hashcache.known_under(self._rootpath)
        found = {}
        scan = localscan.scan(self._rootpath, self.max_depth)
        self.scan_errors = scan.errors
        for relpath, (size, mtime_ns) in scan.files().items():
            known = kept.get(relpath)
            # As it was when it was hashed (see hashcache.get())
            found[relpath] = (size, known[2].get(algorithm) if known and known[:2] == (size, mtime_ns) else None)
        return found

    def content_hash(self, relpath, algorithm, should_stop=None):
        return self.content_hashes(relpath, [algorithm], should_stop)[algorithm]

    def content_hashes(self, relpath, algorithms, should_stop=None):
        # From the hash cache, if it has them (and the file didn't change); the others all in one
        # read of the file, then kept there
        path = os.path.join(self._rootpath, relpath)
        found = {algorithm: hashcache.get(path, algorithm) for algorithm in algorithms}
        needed = [algorithm for algorithm, value in found.items() if value is None]
        if not needed:
            return found
        digests = {algorithm: hashlib.new(algorithm) for algorithm in needed}
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(HASH_READ_SIZE), b''):
                    if should_stop is not None and should_stop():
                        raise dirtree.HashStopped()
                    for digest in digests.values():
                        digest.update(chunk)
        except OSError:
            return found
        computed = {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}
        hashcache.put(path, computed)
        return dict(found, **computed)

    def has_file(self, relpath):
        return os.path.isfile(os.path.join(self._rootpath, relpath))

    def files_by_name(self, progress=None):
        """As DirTree's, but from a listing of the dir (down to max_depth levels), with its files'
        sizes. If progress raises, the listing is stopped."""
        found = collections.defaultdict(list)
        for relpath, (size, _) in localscan.scan(self._rootpath, self.max_depth, progress).files().items():
            found[os.path.basename(relpath)].append((relpath, size))
        return found
