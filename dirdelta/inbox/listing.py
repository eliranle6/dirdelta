"""The inbox's files and dirs, as last listed, and what's kept of them"""
import posixpath

from dirdelta.claude import ai
from dirdelta.drive import clouddirtree
from dirdelta.inbox.formatting import is_at_or_under
from dirdelta.trees import localdiskdirtree
from dirdelta.trees import paths


class Listing(object):
    """The inbox's files and dirs (InboxSort's)"""

    # The inbox's files

    def _inbox_files(self):
        """The inbox's files' relpaths (in it), each dir's together, sorted; their sizes and hashes kept
        for what goes through all of them (see _listed())"""
        self._listing = self._inbox_tree.listed('sha1')
        return sorted(self._listing, key=lambda relpath: relpath.split('/'))

    def _listed(self, relpath):
        """(size, SHA-1 if it's known) of the inbox's file, as last listed, or else as it is"""
        return self._listing.get(relpath) or (self._size(relpath), self._inbox_tree.known_hash(relpath, 'sha1'))

    def _is_in_inbox(self, relpath):
        """Whether the sorted tree's relpath is at or under the inbox, if the inbox is in it"""
        return self._inbox_in_root is not None and is_at_or_under(relpath, self._inbox_in_root)

    def _size(self, relpath):
        return self._inbox_tree.file_size(relpath)

    def _cache_key(self, file):
        """What Claude said of the inbox's file is kept by its contents' hash, once it's known; else,
        or from before, by its path and size"""
        return self._keys(file, self._inbox_tree.known_hash(file.relpath, 'sha1'))

    def _keys(self, file, sha1):
        path_key = self._path_key(file.relpath, file.size)
        return [ai.hash_key(sha1), path_key] if sha1 else [path_key]

    def _path_key(self, relpath, size):
        return ai.path_key(posixpath.join(self.inbox_path, relpath), size)

    def _load_cached(self, relpaths):
        files = [ai.File(relpath, None, self._listed(relpath)[0]) for relpath in relpaths]
        descriptions, recommendations = ai.cached(files, lambda file: self._keys(file, self._listed(file.relpath)[1]),
                                                  self.root_path)
        # The dirs' by their keys now: the ones that changed since are dropped
        keys = {dirpath: self._dir_key(dirpath, count, size)
                for dirpath, (count, size) in self._dir_stats(relpaths).items()}
        self._claude.load(descriptions, recommendations, keys, ai.cached_dirs(keys, self.root_path))

    # The inbox's dirs

    def _dir_stats(self, relpaths):
        """{dir relpath: (how many files, their total size)} of each dir that the inbox's files at
        relpaths are in (not the root)"""
        stats = {}
        for relpath in relpaths:
            size = self._listed(relpath)[0] or 0
            parts = relpath.split('/')[:-1]
            for depth in range(1, len(parts) + 1):
                count, total = stats.get('/'.join(parts[:depth]), (0, 0))
                stats['/'.join(parts[:depth])] = (count + 1, total + size)
        return stats

    def _dir_key(self, dirpath, count, size):
        return ai.dir_key(posixpath.join(self.inbox_path, dirpath), count, size)

    def _whole_dir(self, relpaths, selected):
        """The dir at selected, if relpaths are all its files (as Enter on it picks them; not the
        inbox's root), else None"""
        if not selected or selected in relpaths:
            return None
        under = [relpath for relpath in self._listing if is_at_or_under(relpath, selected)]
        return selected if under and set(under) == set(relpaths) else None


def tree_of(path):
    """The tree of a replica path on its own: a Drive folder's (from the cache), or a local dir's
    (not scanned)"""
    if paths.is_cloud_path(path):
        return clouddirtree.factory(path)
    return localdiskdirtree.LocalReplica(path)


# One way for all (see paths.normalized())
normalized = paths.normalized
