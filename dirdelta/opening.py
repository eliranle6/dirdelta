"""Opening a picker's files with their programs (xdg-open), as if double-clicked: Ctrl-X on the
selected one in the inbox's and a sync's file pickers, or Open in their action menus for the picked
ones. A Drive file is downloaded first (or found downloaded, see downloads.py). It's done in the
background, and the picker's bottom line says how it went (Opener.status_parts())."""
import os
import posixpath
import subprocess
import threading
import time

from dirdelta import downloads
from dirdelta import localdiskdirtree

# The file pickers' key that opens the selected file (Ctrl-X), and its keys row's hint
KEY = '\x18'
KEY_HINT = ('Ctrl-X', 'open')
# How long the bottom line says a file was opened, in seconds
SHOWN_FOR = 5
# How many picked files the action menus' Open opens at most (each in a window of its own)
MAX_OPENED = 10
# The bottom line's color for it
COLOR = 'yellow'


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


class Opener(object):
    """Opens files of tree (a DirTree), at relpaths under its root_rel (a dir's relpath in it, ''
    its root), e.g. an inbox's in the tree it shares with the sorted tree. Drive is asked under
    drive_lock (a threading.Lock), if given, so it's one request at a time with whatever else asks
    it."""

    def __init__(self, tree, root_rel='', drive_lock=None):
        self._tree = tree
        self._root_rel = root_rel
        self._drive_lock = drive_lock or threading.Lock()
        # What the bottom line says, and until when (None: while it's being done)
        self._note = None

    def open_in_background(self, relpaths, files):
        """Open the files at relpaths (relative to root_rel), on a thread of its own. files: the
        relpaths that are files (the rest are dirs: a local one is opened too, in the file manager;
        a Drive one can't be). Returns the thread."""
        thread = threading.Thread(target=self.open, args=(list(relpaths), set(files)), daemon=True)
        thread.start()
        return thread

    def open(self, relpaths, files):
        """Open the files at relpaths (see open_in_background()), one after another"""
        opened, failed = [], []
        for number, relpath in enumerate(relpaths, 1):
            name = self._name(relpath)
            try:
                path = self._local_path(relpath, relpath in files,
                                        "%s (%d of %d)" % (name, number, len(relpaths)) if len(relpaths) > 1 else name)
                # Its own session, so it outlives the picker (and dirdelta), and says nothing on
                # its screen
                subprocess.Popen(['xdg-open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                opened.append(name)
            except OSError as error:
                failed.append((name, error))
        if failed:
            name, error = failed[-1]
            text = "Couldn't open %s: %s" % (name, error)
            if len(failed) > 1:
                text = "Couldn't open %s (%s: %s)" % (_files(len(failed)), name, error)
            if opened:
                text += "; opened %s" % (opened[0] if len(opened) == 1 else _files(len(opened)),)
        else:
            text = "Opened %s" % (opened[0] if len(opened) == 1 else _files(len(opened)),)
        self._note = (text, time.monotonic() + SHOWN_FOR)

    def status(self):
        """What the bottom line says of opening files now ('' nothing)"""
        note = self._note
        if note is not None and (note[1] is None or time.monotonic() < note[1]):
            return note[0]
        return ''

    def status_parts(self):
        """status(), as a picker.status()'s parts ([(text, color)], none for nothing)"""
        status = self.status()
        return [(status, COLOR)] if status else []

    def _name(self, relpath):
        return os.path.basename(relpath) or os.path.basename(self._path()) or self._path()

    def _full(self, relpath):
        """relpath's relpath in the tree"""
        return posixpath.join(self._root_rel, relpath) if self._root_rel and relpath else self._root_rel or relpath

    def _path(self, relpath=''):
        """relpath's path, the tree's (local, or a cloud path)"""
        full = self._full(relpath)
        return posixpath.join(self._tree.fullpath(), full) if full else self._tree.fullpath()

    def _local_path(self, relpath, is_file, shown_name):
        """The local path to open relpath at: a Drive file's downloaded. Raises OSError if it can't
        be."""
        if isinstance(self._tree, localdiskdirtree.LocalDiskDirTree):
            return os.path.join(self._tree.fullpath(), self._full(relpath))
        if not is_file:
            raise OSError("a Google Drive folder can't be opened here")
        full = self._full(relpath)
        reason = self._tree.cant_fetch(full)
        if reason is not None:
            raise OSError(reason)
        self._note = ("Downloading %s to open it..." % (shown_name,), None)
        with self._drive_lock:
            return downloads.get(self._path(relpath), self._tree.file_size(full),
                                 lambda local_path: self._tree.fetch_file(full, local_path))
