"""The web picker's ends of the pipes dirdelta's picker makes for treepicker (see
docs/treepicker-integration.md): reading what's sent to it (--updates, --preview, --side-select), and
writing what it says (--selection, --notify-fd). The web picker owns these fds, as treepicker would:
it closes each once it's done with it."""
import os
import threading


def read_records(fd, on_record):
    """Call on_record(text) for each '\\0'-ended record read from fd, on a thread of its own, until the
    other end closes; then close fd. Returns the thread."""
    def run():
        pending = b''
        try:
            for chunk in iter(lambda: os.read(fd, 65536), b''):
                records = (pending + chunk).split(b'\0')
                pending = records.pop()
                for record in records:
                    on_record(record.decode('utf-8', 'surrogateescape'))
        except OSError:
            pass
        finally:
            _close(fd)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class Writer(object):
    """A pipe the picker writes '\\0'-ended records to, from any thread, until it's closed"""

    def __init__(self, fd):
        self._fd = fd
        self._lock = threading.Lock()

    def write(self, *records):
        data = b''.join(record.encode('utf-8', 'surrogateescape') + b'\0' for record in records)
        with self._lock:
            if self._fd is None:
                return
            try:
                while data:
                    data = data[os.write(self._fd, data):]
            except OSError:
                pass

    def close(self):
        with self._lock:
            if self._fd is not None:
                _close(self._fd)
                self._fd = None


def read_file(path):
    """The '\\0'-ended records of the file at path (e.g. --picked's), or none if there's no path"""
    if path is None:
        return []
    with open(path, 'rb') as records:
        return [record.decode('utf-8', 'surrogateescape') for record in records.read().split(b'\0')[:-1]]


def _close(fd):
    try:
        os.close(fd)
    except OSError:
        pass
