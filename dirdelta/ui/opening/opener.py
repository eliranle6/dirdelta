"""Opener: opens a tree's files, downloading Drive's first; its queue and status are mixins here"""
import os
import threading
import time

from dirdelta.trees import localdiskdirtree
from dirdelta.ui.opening import names
from dirdelta.ui.opening.downloading import Downloading
from dirdelta.ui.opening.names import COLOR, CONFIRM_FOR, _DOWNLOADING, _files, _short_dir
from dirdelta.ui.opening.status import Status
from dirdelta.util import downloads
from dirdelta.util import text


class Opener(Downloading, Status):


    """Opens files of tree (a DirTree), by their relpaths. Files are downloaded under drive_lock (a
    threading.Lock), if given, shared with whatever else downloads them or changes tree: two downloads
    of a file would write the same .part (downloads.get())."""

    def __init__(self, tree, drive_lock=None):
        self._tree = tree
        self._drive_lock = drive_lock or threading.Lock()
        self._lock = threading.Lock()
        # The files to open, in turn ([(relpath, whether it's a file)]), and whether a worker is
        # opening them
        self._queue = []
        self._is_running = False
        # Each downloaded file's state (_WAITING, ...) and bytes done, while they're downloaded and
        # for SHOWN_FOR after; and every one that had a tag (so a picker shows it without one again)
        self._states = {}
        self._tagged = set()
        # The downloads since the worker started: their sizes in all, and done (of the ones done)
        self._total = self._done = 0
        self._nr_total = self._nr_done = 0
        # What was opened, or failed to be, since the worker started (names; (name, error))
        self._opened, self._failed = [], []
        # What the status bar says (text, color, until when) when nothing's being downloaded
        self._note = None
        # Ctrl-X's question: the files it's about, until when
        self._asked = None

    # Asking first

    def to_download(self, relpaths, files):
        """[(relpath, size)] of relpaths (of files: the rest are dirs) that are Drive files not
        downloaded yet"""
        if localdiskdirtree.is_local(self._tree):
            return []
        found = []
        for relpath in relpaths:
            if relpath in files and self._tree.cant_fetch(relpath) is None:
                size = self._tree.file_size(relpath)
                if not downloads.is_downloaded(self._path(relpath), size):
                    found.append((relpath, size))
        return found

    def question(self, relpaths, files):
        """What to ask before opening relpaths (of files): None if nothing (at most one file to
        download)"""
        found = self.to_download(relpaths, files)
        if len(found) <= 1:
            return None
        return "download %s (%s) into %s, and open them" % (
            _files(len(found)), text.format_size(sum(size or 0 for _, size in found)), _short_dir())

    def press(self, relpaths, files):
        """Ctrl-X on relpaths (of files): open them, unless there's more than one file to download
        and they weren't asked about just now (with the same files), in which case the status bar
        asks to press it again"""
        relpaths = list(relpaths)
        if len(relpaths) > names.MAX_OPENED:
            self._say("Can't open %s at once (at most %d): pick fewer" % (_files(len(relpaths)), names.MAX_OPENED))
            return
        asked, self._asked = self._asked, None
        question = self.question(relpaths, files)
        if question is not None and not (asked and asked[0] == relpaths and time.monotonic() < asked[1]):
            self._asked = (relpaths, time.monotonic() + CONFIRM_FOR)
            self._note = ("Ctrl-X again: %s" % (question,), COLOR, time.monotonic() + CONFIRM_FOR)
            return
        self._note = None
        self.open_in_background(relpaths, files)

    # Opening

    def open_in_background(self, relpaths, files):
        """Open the files at relpaths , on a thread of their own, after the
        ones already being opened. files: the relpaths that are files (the rest are dirs: a local
        one is opened too, in the file manager; a Drive one can't be). Returns the thread, or None
        if one was opening files already (and goes on with these)."""
        if self._enqueue(relpaths, files):
            thread = threading.Thread(target=self._work, daemon=True)
            thread.start()
            return thread
        return None

    def open(self, relpaths, files):
        """Open the files at relpaths (see open_in_background()) on this thread, if none other is
        opening files (else that one opens them)"""
        if self._enqueue(relpaths, files):
            self._work()


    def local_path(self, relpath, max_size=None):
        """Where the file at relpath is on this machine, to read it there: a Drive file's downloaded
        (unless it was), on this thread; None if it's one that can't be, or is bigger than max_size.
        Raises OSError if it can't be downloaded."""
        if not localdiskdirtree.is_local(self._tree):
            if self._tree.cant_fetch(relpath) is not None or (max_size is not None and
                                                           (self._tree.file_size(relpath) or 0) > max_size):
                return None
        return self._local_path(relpath, True)

    def _local_path(self, relpath, is_file):
        """The local path to open relpath at: a Drive file's downloaded (its progress kept, for
        the status bar and its tag). Raises OSError if it can't be."""
        if localdiskdirtree.is_local(self._tree):
            return os.path.join(self._tree.fullpath(), relpath)
        if not is_file:
            raise OSError("a Google Drive folder can't be opened here")
        reason = self._tree.cant_fetch(relpath)
        if reason is not None:
            raise OSError(reason)
        state = self._states.get(relpath)

        def progress(done):
            if state is not None:
                state[1] = done

        def fetch(local_path):
            if state is not None:
                state[0] = _DOWNLOADING
            self._tree.fetch_file(relpath, local_path, progress=progress)
        with self._drive_lock:
            return downloads.get(self._path(relpath), self._tree.file_size(relpath), fetch)
