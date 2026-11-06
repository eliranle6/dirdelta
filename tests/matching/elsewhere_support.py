"""What the tests of finding files elsewhere share: fake replicas, a send() that keeps what's sent, a scripted selection"""
import collections
import os
import unittest

from dirdelta.matching import elsewhere
from dirdelta.trees import dirtree
from dirdelta.ui import picker


class SizedTree(dirtree.DirTree):
    """A DirTree whose files have the given sizes (and dates taken)"""
    def __init__(self, rootpath, sizes, dates=None, hashes=None, times=None):
        super(SizedTree, self).__init__(rootpath)
        self._sizes = sizes
        self._dates = dates or {}
        self._hashes = hashes or {}
        self._times = times or {}
        # The files whose hashes aren't known without working them out (unlike Drive's)
        self.slow = set()
        self.dates_read = []
        self.hashed = []
        for relpath in sizes:
            self.add_file_by_relpath(relpath)

    def file_size(self, relpath):
        return self._sizes.get(relpath)

    def date_taken(self, relpath):
        self.dates_read.append(relpath)
        return self._dates.get(relpath)

    def content_hash(self, relpath, algorithm, should_stop=None):
        # Like Drive's: SHA-256s known. As if working it out took a while: asked once whether to stop.
        if should_stop is not None and should_stop():
            raise dirtree.HashStopped()
        self.hashed.append(relpath)
        return self._hashes.get(relpath) if algorithm == 'sha256' else None

    def known_hashes(self, relpath):
        return ('sha256',) if self._hashes.get(relpath) and relpath not in self.slow else ()

    def modified_time(self, relpath):
        return self._times.get(relpath)


class Sent(object):
    """A send() for find_previews(): keeps what's sent"""
    def __init__(self):
        self.previews = {}
        self.defaults = []

    def __call__(self, found=None, default=None):
        # Their text (their styles are picker's: see picker.styled())
        self.previews.update({relpath: [picker.unstyled(line) for line in lines]
                              for relpath, lines in (found or {}).items()})
        if default is not None:
            self.defaults.append(default)


def previews_of(relpaths, src, dst):
    sent = Sent()
    elsewhere.find_previews(relpaths, src, elsewhere.Index(dst), sent)
    return sent


class ScriptedSelection(object):
    """A picker.Selection that moves to each of moves in turn (None: a wait that times out), then
    the picker is gone; at, if given, says where it is when asked (else at the last move)"""
    def __init__(self, moves, at=None):
        self._moves = list(moves)
        self._at = at
        self._last = None

    def wait_next(self, timeout=None):
        if not self._moves:
            raise picker.PickerClosed()
        move = self._moves.pop(0)
        if move is not None:
            self._last = move
        return move

    def is_at(self, relpath):
        return (self._at(relpath) if self._at is not None else self._last == relpath)


class ChangingDuringAListing(dirtree.DirTree):
    """A replica in which something changes while it's listed, after what's listed is read"""
    def __init__(self, listed, during):
        super(ChangingDuringAListing, self).__init__('/x')
        self.listed = listed
        self.during = during
        self.sizes = {}

    def files_by_name(self, progress=None):
        found = collections.defaultdict(list)
        for relpath, size in self.listed.items():
            found[os.path.basename(relpath)].append((relpath, size))
        during, self.during = self.during, None
        if during is not None:
            during()
        return found

    def file_size(self, relpath):
        return self.sizes.get(relpath)


class SlowReplica(dirtree.DirTree):
    """A replica whose file's being read when something happens"""
    def __init__(self):
        super(SlowReplica, self).__init__('/x')
        self.during_read = lambda: None

    def content_hashes(self, relpath, algorithms, should_stop=None):
        self.during_read()
        return {algorithm: 'read-of-' + relpath for algorithm in algorithms}

    def date_taken(self, relpath):
        self.during_read()
        return 'date-of-' + relpath


if __name__ == '__main__':
    unittest.main()
