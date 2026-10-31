"""Opening a picker's files with their programs (xdg-open), as if double-clicked: Ctrl-X in the
inbox's and a sync's file pickers (on the picked files, or else the selected one), or Open in their
action menus. A Drive file is downloaded first, into downloads.DOWNLOADS_DIR (or found downloaded
there). It's done in the background, one file after another, while the picker is shown: its status
bar says how far the downloads got, in all (Opener.status_parts()), and each file being downloaded
says how far it got, in a tag after its name (Opener.tags()), as hashing's do.

More than one file to download is asked about first: Ctrl-X asks on the status bar, and pressed
again soon (in CONFIRM_FOR seconds) on the same files, goes ahead (so the picker stays); the menu's
Open asks on a screen of its own (confirm())."""
import os
import posixpath
import subprocess
import threading
import time

from dirdelta import downloads
from dirdelta import elsewhere
from dirdelta import localdiskdirtree
from dirdelta import picker

# The file pickers' key that opens the picked files, or the selected one (Ctrl-X), and its keys
# row's hint
KEY = '\x18'
KEY_HINT = ('Ctrl-X', 'open')
# How long the status bar says what was opened, in seconds; and how long Ctrl-X's question waits
# for it again
SHOWN_FOR = 5
CONFIRM_FOR = 10
# How many files are opened at once at most (each in a window of its own)
MAX_OPENED = 10
# The status bar's colors: of a note (what was opened, or why not) and the question, and of the
# downloads' progress (orange, as hashing's)
COLOR = 'yellow'
PROGRESS_COLOR = 'orange'
# The tags after a downloaded file's name: waiting for its turn, how far it got, opened, failed
WAITING_TAG = "[↓ waiting]"
DOWNLOADING_TAG = "[↓ %d%%]"
OPENED_TAG = "[↓ opened]"
FAILED_TAG = "[↓ failed]"


def tag_style(tag):
    """A tag's style (see picker.styled()): downloading in orange, as its status, opened in its note's
    color"""
    return {WAITING_TAG: 'grey', OPENED_TAG: COLOR, FAILED_TAG: 'red'}.get(tag, PROGRESS_COLOR)
# What the confirmation's options are
CONFIRM_NO = 'No'
CONFIRM_YES = 'Yes, download and open them'

_WAITING, _DOWNLOADING, _OPENED, _FAILED = 'waiting', 'downloading', 'opened', 'failed'


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


def _short_dir():
    """DOWNLOADS_DIR, with ~ for the home dir"""
    home = os.path.expanduser('~')
    path = downloads.DOWNLOADS_DIR
    return '~' + path[len(home):] if path == home or path.startswith(home + os.sep) else path


class Opener(object):
    """Opens files of tree (a DirTree), at relpaths under its root_rel (a dir's relpath in it, ''
    its root), e.g. an inbox's in the tree it shares with the sorted tree. Drive is asked under
    drive_lock (a threading.Lock), if given, so it's one request at a time with whatever else asks
    it."""

    def __init__(self, tree, root_rel='', drive_lock=None):
        self._tree = tree
        self._root_rel = root_rel
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
        if isinstance(self._tree, localdiskdirtree.LocalDiskDirTree):
            return []
        found = []
        for relpath in relpaths:
            full = self._full(relpath)
            if relpath in files and self._tree.cant_fetch(full) is None:
                size = self._tree.file_size(full)
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
            _files(len(found)), elsewhere.format_size(sum(size or 0 for _, size in found)), _short_dir())

    def press(self, relpaths, files):
        """Ctrl-X on relpaths (of files): open them, unless there's more than one file to download
        and they weren't asked about just now (with the same files), in which case the status bar
        asks to press it again"""
        relpaths = list(relpaths)
        if len(relpaths) > MAX_OPENED:
            self._say("Can't open %s at once (at most %d): pick fewer" % (_files(len(relpaths)), MAX_OPENED))
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
        """Open the files at relpaths (relative to root_rel), on a thread of their own, after the
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

    def _enqueue(self, relpaths, files):
        """Queue the files; returns whether a worker is to be started (none is running)"""
        to_download = dict(self.to_download(relpaths, files))
        with self._lock:
            if not self._is_running:
                self._total = self._done = self._nr_total = self._nr_done = 0
                self._opened, self._failed = [], []
                self._states = {}
            for relpath in relpaths:
                self._queue.append((relpath, relpath in files))
                if relpath in to_download:
                    self._states[relpath] = [_WAITING, 0]
                    self._tagged.add(relpath)
                    self._total += to_download[relpath] or 0
                    self._nr_total += 1
            is_starting = not self._is_running
            self._is_running = True
        return is_starting

    def _work(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._is_running = False
                    self._note = (self._summary(), COLOR, time.monotonic() + SHOWN_FOR)
                    return
                relpath, is_file = self._queue.pop(0)
            name = self._name(relpath)
            try:
                path = self._local_path(relpath, is_file)
                # Its own session, so it outlives the picker (and dirdelta), and says nothing on
                # its screen
                subprocess.Popen(['xdg-open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                self._end(relpath, _OPENED)
                self._opened.append(name)
            except OSError as error:
                self._end(relpath, _FAILED)
                self._failed.append((name, error))

    def _end(self, relpath, state):
        with self._lock:
            if relpath in self._states and self._states[relpath][0] != state:
                self._states[relpath][0] = state
                self._done += self._size(relpath)
                self._nr_done += 1

    def _summary(self):
        """What the status bar says once they're all done"""
        opened, failed = self._opened, self._failed
        if not failed:
            return "Opened %s" % (opened[0] if len(opened) == 1 else _files(len(opened)),)
        name, error = failed[-1]
        text = ("Couldn't open %s: %s" % (name, error) if len(failed) == 1 else
                "Couldn't open %s (%s: %s)" % (_files(len(failed)), name, error))
        if opened:
            text += "; opened %s" % (opened[0] if len(opened) == 1 else _files(len(opened)),)
        return text

    def _local_path(self, relpath, is_file):
        """The local path to open relpath at: a Drive file's downloaded (its progress kept, for
        the status bar and its tag). Raises OSError if it can't be."""
        if isinstance(self._tree, localdiskdirtree.LocalDiskDirTree):
            return os.path.join(self._tree.fullpath(), self._full(relpath))
        if not is_file:
            raise OSError("a Google Drive folder can't be opened here")
        full = self._full(relpath)
        reason = self._tree.cant_fetch(full)
        if reason is not None:
            raise OSError(reason)
        state = self._states.get(relpath)

        def progress(done):
            if state is not None:
                state[1] = done

        def fetch(local_path):
            if state is not None:
                state[0] = _DOWNLOADING
            self._tree.fetch_file(full, local_path, progress=progress)
        with self._drive_lock:
            return downloads.get(self._path(relpath), self._tree.file_size(full), fetch)

    # What the picker shows

    def status(self):
        """What the status bar says of opening files now ('' nothing)"""
        return ''.join(text for text, _ in self.status_parts())

    def status_parts(self):
        """The status bar's part of opening files, as picker.status()'s ([(text, color)]; none for
        nothing): how far the downloads got while there are any; else what was opened, or why not,
        or Ctrl-X's question, for a while"""
        with self._lock:
            if self._is_running and self._nr_done < self._nr_total:
                downloading = [relpath for relpath, (state, _) in self._states.items() if state == _DOWNLOADING]
                done = self._done + sum(self._states[relpath][1] for relpath in downloading)
                percent = done * 100 // self._total if self._total else 0
                if self._nr_total == 1:
                    relpath, = self._states
                    text = "Downloading %s to open it: %d%% (%s of %s)" % (
                        self._name(relpath), percent, elsewhere.format_size(done), elsewhere.format_size(self._total))
                else:
                    text = "Downloading to open: %d of %d files, %d%% (%s of %s)" % (
                        min(self._nr_done + 1, self._nr_total), self._nr_total, percent,
                        elsewhere.format_size(done), elsewhere.format_size(self._total))
                return [(text, PROGRESS_COLOR)]
            note = self._note
        if note is not None and time.monotonic() < note[2]:
            return [(note[0], note[1])]
        return []

    def tags(self):
        """{relpath: its tag} of the files being downloaded (or waiting to be), and of the ones
        downloaded and opened (or that failed), until the status bar stops saying so; and '' for
        the ones that had a tag since, to show them without one again"""
        with self._lock:
            note = self._note
            is_shown = self._is_running or (note is not None and time.monotonic() < note[2])
            tags = {relpath: '' for relpath in self._tagged}
            if is_shown:
                for relpath, (state, done) in self._states.items():
                    tags[relpath] = (WAITING_TAG if state == _WAITING else
                                     DOWNLOADING_TAG % (done * 100 // (self._size(relpath) or 1),)
                                     if state == _DOWNLOADING else
                                     OPENED_TAG if state == _OPENED else FAILED_TAG)
            return tags

    def _say(self, text):
        self._note = (text, COLOR, time.monotonic() + SHOWN_FOR)

    # Paths

    def _size(self, relpath):
        return self._tree.file_size(self._full(relpath)) or 0

    def _name(self, relpath):
        return os.path.basename(relpath) or os.path.basename(self._path()) or self._path()

    def _full(self, relpath):
        """relpath's relpath in the tree"""
        return posixpath.join(self._root_rel, relpath) if self._root_rel and relpath else self._root_rel or relpath

    def _path(self, relpath=''):
        """relpath's path, the tree's (local, or a cloud path)"""
        full = self._full(relpath)
        return posixpath.join(self._tree.fullpath(), full) if full else self._tree.fullpath()


def confirm(opener, relpaths, files, label=None):
    """Whether to open relpaths (of files) with opener, as the action menu's Open: asked on a
    screen of its own (No first) if there's more than one file to download (else yes at once)"""
    question = opener.question(relpaths, files)
    if question is None:
        return True
    found = opener.to_download(relpaths, files)
    lines = ["Open %s? First, %s:" % (_files(len(relpaths)), question.replace(", and open them", ""))]
    lines += ["  %s (%s)" % (relpath, elsewhere.format_size(size or 0)) for relpath, size in found[:MAX_OPENED]]
    answer = picker.pick_option([CONFIRM_NO, CONFIRM_YES], header='\n'.join(lines), label=label, title="Sure?")
    return answer == CONFIRM_YES


def with_tags(shown, opener, name_of):
    """A picker's shown_as result (shown, {relpath: text}) with opener's tags after the files'
    texts: name_of(relpath) is what a file is shown as without one, for the ones shown has none of"""
    for relpath, tag in opener.tags().items():
        text = shown.get(relpath) or name_of(relpath)
        shown[relpath] = text + picker.styled([("  ", None), (tag, tag_style(tag))]) if tag else text
    return shown
