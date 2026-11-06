"""What a picker shows of an opener's work: its status bar, and each file's tag"""
import os
import posixpath
import time

from dirdelta.ui.opening.names import (COLOR,
    DOWNLOADING_TAG,
    FAILED_TAG,
    OPENED_TAG,
    PROGRESS_COLOR,
    SHOWN_FOR,
    WAITING_TAG,
    _DOWNLOADING,
    _OPENED,
    _WAITING)
from dirdelta.util.text import format_size as _size


class Status(object):
    """What's shown (Opener's)"""

    # What the picker shows

    def status(self):
        """What the status bar says of opening files now ('' nothing)"""
        return ''.join(text for text, _ in self.status_parts())

    def status_parts(self):
        """The status bar's part of opening files, as picker.segments()'s ([(text, color)]; none for
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
                        self._name(relpath), percent, _size(done), _size(self._total))
                else:
                    text = "Downloading to open: %d of %d files, %d%% (%s of %s)" % (
                        min(self._nr_done + 1, self._nr_total), self._nr_total, percent,
                        _size(done), _size(self._total))
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
        return self._tree.file_size(relpath) or 0

    def _name(self, relpath):
        return os.path.basename(relpath) or os.path.basename(self._path()) or self._path()

    def _path(self, relpath=''):
        """relpath's path, the tree's (local, or a cloud path)"""
        return posixpath.join(self._tree.fullpath(), relpath) if relpath else self._tree.fullpath()
