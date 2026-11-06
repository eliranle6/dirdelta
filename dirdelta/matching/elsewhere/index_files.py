"""An Index's files: looked up, and kept up to date as they're added, removed and moved"""
import os

from dirdelta.matching.elsewhere.constants import RENAMED_MIN_SIZE, HASH_PREFERENCE


class IndexFiles(object):
    """An Index's files"""

    def relpaths(self):
        """All its files' relpaths, once built"""
        with self._lock:
            return [relpath for files in self._by_name.values() for relpath in files]

    def files_named(self, name):
        """{relpath: size} of the files with the name"""
        with self._lock:
            return dict(self._by_name.get(name, {}))

    def files_sized(self, size):
        """The relpaths of the files of the size, if it's big enough to be in (RENAMED_MIN_SIZE)"""
        with self._lock:
            return set(self._by_size.get(size, set()))

    def hash_algorithms(self):
        """The algorithms of the hashes known of its files without reading them (Drive's, or its
        hashing job's), the fastest to work out first"""
        self._take_hashes()
        with self._lock:
            known = {algorithm for algorithm, _ in self._by_hash}
        return [algorithm for algorithm in HASH_PREFERENCE if algorithm in known]

    def files_hashed(self, algorithm, value):
        """The relpaths of the files whose contents' hash by algorithm is value (of the ones known)"""
        self._take_hashes()
        with self._lock:
            return set(self._by_hash.get((algorithm, value), set()))

    def names_in(self, dirpath):
        with self._lock:
            return set(self._names_by_dir.get(dirpath, set()))

    def date_taken(self, relpath):
        with self._lock:
            if relpath in self._dates_taken:
                return self._dates_taken[relpath]
            nr_removed = self._nr_removed
        # Read without the lock (it reads the file), and kept unless it may be another file's by now
        date = self.replica.date_taken(relpath)
        with self._lock:
            if nr_removed == self._nr_removed:
                self._dates_taken[relpath] = date
        return date

    def modified_time(self, relpath):
        return self.replica.modified_time(relpath)

    def add(self, relpath, size):
        """A file is at relpath now (unless it isn't built yet, when there's nothing to change, or
        it's being built, when it's done after)"""
        with self._lock:
            if self._is_building:
                self._changes_meanwhile.append((self.add, (relpath, size)))
            elif self.is_built() and not self._is_excluded(relpath):
                name = os.path.basename(relpath)
                if relpath not in self._by_name.get(name, {}):
                    self._nr_files += 1
                self._by_name.setdefault(name, {})[relpath] = size
                self._names_by_dir[os.path.dirname(relpath)].add(name)
                if size is not None and size >= RENAMED_MIN_SIZE:
                    self._by_size[size].add(relpath)
                hashes = {algorithm: self.replica.content_hash(relpath, algorithm)
                          for algorithm in self.replica.known_hashes(relpath)}
                self._add_hashes(relpath, hashes)

    def remove(self, relpath):
        with self._lock:
            if self._is_building:
                self._changes_meanwhile.append((self.remove, (relpath,)))
            if self.is_built():
                name = os.path.basename(relpath)
                files = self._by_name.get(name, {})
                if relpath in files:
                    self._nr_files -= 1
                size = files.pop(relpath, None)
                if not files:
                    self._by_name.pop(name, None)
                # (Drive may have another of the name in the dir)
                if not any(os.path.dirname(path) == os.path.dirname(relpath) for path in files):
                    self._names_by_dir.get(os.path.dirname(relpath), set()).discard(name)
                self._by_size.get(size, set()).discard(relpath)
            for algorithm, value in self._hashes.get(relpath, {}).items():
                self._by_hash.get((algorithm, value), set()).discard(relpath)
                self._hashed[algorithm].discard(relpath)
            self._hashes.pop(relpath, None)
            self._dates_taken.pop(relpath, None)
            self._nr_removed += 1

    def move(self, relpath, new_relpath):
        with self._lock:
            # The same file, with the same contents
            hashes = self._hashes.get(relpath)
            if self._is_building:
                self._changes_meanwhile.append((self.move, (relpath, new_relpath)))
            elif self.is_built():
                size = self.files_named(os.path.basename(relpath)).get(relpath)
                if size is None:
                    # Listed after it moved, or not listed
                    size = self.files_named(os.path.basename(new_relpath)).get(new_relpath, self.replica.file_size(new_relpath))
                self.remove(relpath)
                self.add(new_relpath, size)
            else:
                self.remove(relpath)
            if hashes:
                self._add_hashes(new_relpath, hashes)
