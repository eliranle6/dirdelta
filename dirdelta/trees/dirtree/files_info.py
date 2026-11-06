"""What a tree knows of its files: sizes, dates, hashes, and the files by name"""
import collections
import os

from dirdelta.trees import entries


class FilesInfo(object):
    """Its files' info (DirTree's)"""

    def iter_files(self):
        for node in self._tree.all_nodes_itr():
            if isinstance(node.data, entries.FileEntry):
                yield node.data

    def file_size(self, relpath):
        """The size in bytes of the file at relpath, or None if it isn't known"""
        return None

    def date_taken(self, relpath):
        """When the photo at relpath was taken ('YYYY-MM-DD HH:MM:SS'), or None if it isn't one, or
        that isn't known"""
        return None

    def content_hash(self, relpath, algorithm, should_stop=None):
        """The hash (hex) of the contents of the file at relpath by algorithm (a hashlib name, e.g.
        'sha1'), or None if it isn't known (or it can't be read). One that has to read the file
        calls should_stop() as it goes, and raises HashStopped once it says to."""
        return None

    def content_hashes(self, relpath, algorithms, should_stop=None):
        """{algorithm: content_hash()} of the algorithms (one read of the file, for one that reads
        it)"""
        return {algorithm: self.content_hash(relpath, algorithm, should_stop) for algorithm in algorithms}

    def known_hash(self, relpath, algorithm):
        """The file's hash (hex) by algorithm if it's known without reading it (Drive's, or one kept
        in the hash cache), else None"""
        return None

    def listed(self, algorithm):
        """{relpath: (size, its hash by algorithm if it's known without reading it, else None)} of all
        its files, at once (a local one's in one listing and one query, not one of each per file)"""
        return {file_entry.relpath: (self.file_size(file_entry.relpath), self.known_hash(file_entry.relpath, algorithm))
                for file_entry in self.iter_files()}

    def known_hashes(self, relpath):
        """The algorithms whose hashes of the file at relpath are known without reading it (e.g.
        Drive's), the best first"""
        return ()

    def local_path(self, relpath):
        """The file's path on the local disk, if it's there (to read it), or None"""
        return None

    def modified_time(self, relpath):
        """When the file at relpath was last modified (seconds since the epoch), or None if that
        isn't known"""
        return None

    def has_file(self, relpath):
        """Whether there's a file at relpath (e.g. after copying it here, or removing it)"""
        node = self.get_node(relpath)
        return node is not None and isinstance(node.data, entries.FileEntry)

    # How many files files_by_name() goes through between its progress() calls
    FILES_PER_PROGRESS = 1000

    def files_by_name(self, progress=None):
        """{name: [(relpath, size)]} of all the tree's files (size: as file_size()), to find where
        it has a file of a name. progress, if given, is called now and then with how many files
        it has so far (and may raise, to stop it)."""
        found = collections.defaultdict(list)
        for count, file_entry in enumerate(self.iter_files(), 1):
            found[os.path.basename(file_entry.relpath)].append(
                (file_entry.relpath, self.file_size(file_entry.relpath)))
            if progress is not None and count % self.FILES_PER_PROGRESS == 0:
                progress(count)
        return found

    def does_dir_contain_any_files(self):
        return next(self.iter_files(), None) is not None
