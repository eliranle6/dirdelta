"""Copying an import's files from its source (copy()), on a thread of its own: its media files listed,
then each one not copied yet read into a .part file, its SHA-1 worked out as it's read (what tells
whether a replica has it already), then renamed into place. If the source goes (the phone unplugged),
it stops, and goes on where it was when it's run again."""
import hashlib
import os
import threading
import time

from dirdelta.phoneimport import sources
from dirdelta.phoneimport import store

CHUNK = 1 << 20
# How often the manifest is saved while copying, at most (seconds)
SAVE_INTERVAL = 2

# {import id: its Copying}, the ones running or done since the daemon started
_copyings = {}
_lock = threading.Lock()


class Copying(object):
    """A copy of an import's files: its phase ('listing', 'copying', 'done', or 'waiting' for the
    source, which can't be read), and what's said of it"""

    def __init__(self, found):
        self.import_ = found
        self.phase = 'listing'
        self.message = ''
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        found = self.import_
        try:
            found.add(sources.media_files(found.source))
        except OSError as error:
            self._wait("Can't read %s (%s): plug the phone in (and allow file transfer) to go on." % (found.source, error.strerror))
            return
        self.phase = 'copying'
        last_save = time.monotonic()
        with found.lock:
            pending = [relpath for relpath, info in found.files.items() if info['state'] == store.PENDING]
        for relpath in pending:
            try:
                sha1 = _copy(os.path.join(found.source, relpath), found.local_path(relpath))
            except OSError as error:
                found.save()
                if not os.path.isdir(found.source):
                    self._wait("The source is gone (%s): plug it in again to go on." % (error.strerror,))
                    return
                self.message = "Couldn't copy %s: %s" % (relpath, error.strerror)
                continue
            with found.lock:
                found.files[relpath].update(state=store.COPIED, sha1=sha1)
            if time.monotonic() - last_save > SAVE_INTERVAL:
                found.save()
                last_save = time.monotonic()
        found.save()
        self.phase = 'done'

    def _wait(self, message):
        self.phase = 'waiting'
        self.message = message


def copy(found):
    """Start copying the import found (a store.Import) unless it's being copied; returns its Copying"""
    with _lock:
        copying = _copyings.get(found.id)
        if copying is not None and copying.thread.is_alive():
            return copying
        copying = _copyings[found.id] = Copying(found)
        copying.thread.start()
        return copying


def copying_of(import_id):
    """The import's Copying since the daemon started, or None"""
    with _lock:
        return _copyings.get(import_id)


def _copy(source_path, path):
    """Copy the file at source_path to path (by a .part file, renamed once it's whole); returns its SHA-1"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part_path = path + '.part'
    digest = hashlib.sha1()
    with open(source_path, 'rb') as source, open(part_path, 'wb') as part:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            digest.update(chunk)
            part.write(chunk)
    stat = os.stat(source_path)
    os.utime(part_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(part_path, path)
    return digest.hexdigest()
