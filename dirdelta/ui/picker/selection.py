"""Where a picker's selection is, as treepicker says, and the keys it was told of"""
import os
import threading


class PickerClosed(Exception):
    """Raised by pick_files()'s previews' send(), and its on_selection's Selection, once the picker
    is gone"""


class Selection(object):
    """Where a pick_files() picker's selection is (a relpath, '' for the root), as treepicker says
    while it's shown, for its on_selection"""

    def __init__(self):
        self._condition = threading.Condition()
        self._relpath = None
        # How many times it moved, and how many of them wait_next() has returned
        self._nr_moves = self._nr_seen = 0
        self._is_closed = False

    def wait_next(self, timeout=None):
        """The selection, once it has moved since wait_next() last returned it (or at first), or
        None if timeout (seconds) passes first. Raises PickerClosed once the picker is gone."""
        with self._condition:
            self._condition.wait_for(lambda: self._is_closed or self._nr_moves != self._nr_seen,
                                     timeout)
            if self._is_closed:
                raise PickerClosed()
            if self._nr_moves == self._nr_seen:
                return None
            self._nr_seen = self._nr_moves
            return self._relpath

    def is_at(self, relpath):
        """Whether the selection is at relpath now. Raises PickerClosed once the picker is gone."""
        with self._condition:
            if self._is_closed:
                raise PickerClosed()
            return self._relpath == relpath

    def _move(self, relpath):
        with self._condition:
            self._relpath = relpath
            self._nr_moves += 1
            self._condition.notify_all()

    def _close(self):
        with self._condition:
            self._is_closed = True
            self._condition.notify_all()


def follow_side(selection, follow, fd):
    """Send treepicker the side tree's relpath to select (see Side) each time the selection moves,
    until it's gone"""
    try:
        while True:
            relpath = follow(selection.wait_next())
            if relpath is not None:
                os.write(fd, ((relpath or '.') + '\0').encode('utf-8', 'surrogateescape'))
    except (PickerClosed, BrokenPipeError):
        pass


def read_selection(fd, selections):
    """Move each of selections as treepicker says the selection moves (each path ending with '\0'),
    until it stops saying (it's gone)"""
    pending = b''
    try:
        for chunk in iter(lambda: os.read(fd, 4096), b''):
            paths = (pending + chunk).split(b'\0')
            pending = paths.pop()
            for path in paths:
                path = path.decode('utf-8', 'surrogateescape')
                for selection in selections:
                    selection._move('' if path == '.' else path)
    except OSError:
        pass
    finally:
        for selection in selections:
            selection._close()


def read_notifications(fd, on_notify):
    """Call on_notify(key, selected relpath, picked relpaths) for each of treepicker's --notify
    records (the key, the selected node's path, the picked ones', each ending with '\\0', and an
    empty item to end it), until it's gone"""
    items, pending = [], b''
    try:
        for chunk in iter(lambda: os.read(fd, 4096), b''):
            parts = (pending + chunk).split(b'\0')
            pending = parts.pop()
            for part in parts:
                if part:
                    items.append(part.decode('utf-8', 'surrogateescape'))
                    continue
                if len(items) >= 2:
                    key, selected, picked = items[0], items[1], items[2:]
                    on_notify(key, '' if selected == '.' else selected, picked)
                items = []
    except OSError:
        pass
