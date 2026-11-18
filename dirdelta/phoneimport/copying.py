"""Reading a source into its pool (read()), on a thread of its own, one at a time for a source: listing
its media files (names, sizes and times: what's compared first), then copying the files asked for,
each into a .part file, its SHA-1 worked out as it's read (the stronger comparison), then renamed into
place. A Drive folder is listed from the Drive cache (read anew from Drive when it's listed again), its
files already hashed by Drive, and downloaded when they're needed. If the source goes (the phone
unplugged), it stops, and goes on when it's asked again."""
import hashlib
import os
import threading

from dirdelta.phoneimport import pool as pools
from dirdelta.phoneimport import sources
from dirdelta.trees import paths

CHUNK = 1 << 20
# How many files are copied between the pool's saves
SAVE_EVERY = 20

# {source: its Reading}, the ones running or done since the daemon started
_readings = {}
_lock = threading.Lock()


class Reading(object):
    """Reading a source: its phase ('listing', 'copying', 'done', or 'waiting' for the source, which
    can't be read), what's said of it, and how many of the files asked for are copied"""

    def __init__(self, source_pool):
        self.pool = source_pool
        self.phase = 'done'
        self.message = ''
        self.nr_asked = self.nr_copied = 0
        self._is_listing = False
        self._is_reading_drive = False
        self._wanted = []
        self._cond = threading.Lock()
        self._is_running = False
        self.thread = None

    def ask(self, is_listing, relpaths, from_drive=False):
        """List the source again (if is_listing; a Drive folder read anew from Drive if from_drive), and
        copy the files at relpaths (if they aren't)"""
        with self._cond:
            self._is_reading_drive = self._is_reading_drive or (is_listing and from_drive)
            if not self._is_running and self.phase == 'done':
                self.nr_asked = self.nr_copied = 0
            self._is_listing = self._is_listing or is_listing
            with self.pool.lock:
                wanted = [relpath for relpath in relpaths if not self.pool.files.get(relpath, {}).get('copied')]
            queued = set(self._wanted)
            new = [relpath for relpath in wanted if relpath not in queued]
            self._wanted.extend(new)
            self.nr_asked += len(new)
            if not self._is_running:
                self._is_running = True
                self.message = ''
                self.phase = 'listing' if self._is_listing else 'copying'
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _run(self):
        source_pool = self.pool
        while True:
            with self._cond:
                is_listing, self._is_listing = self._is_listing, False
                from_drive, self._is_reading_drive = self._is_reading_drive and is_listing, self._is_reading_drive and not is_listing
                relpath = self._wanted.pop(0) if self._wanted and not is_listing else None
                if not is_listing and relpath is None:
                    source_pool.save()
                    self.phase = 'done'
                    self._is_running = False
                    return
            if is_listing:
                self.phase = 'listing'
                try:
                    _list(source_pool, from_drive)
                except OSError as error:
                    return self._wait("Can't read %s (%s): plug the phone in (and allow file transfer) to go on."
                                      % (source_pool.source, error.strerror))
                continue
            self.phase = 'copying'
            try:
                sha1 = _fetch(source_pool, relpath)
            except OSError as error:
                if not source_pool.is_drive and not os.path.isdir(source_pool.source):
                    with self._cond:
                        self._wanted.insert(0, relpath)
                    return self._wait("The phone is gone (%s): plug it in again to go on." % (error.strerror,))
                self.message = "Couldn't copy %s: %s" % (relpath, error.strerror)
                self.nr_asked -= 1
                continue
            source_pool.copied(relpath, sha1)
            self.nr_copied += 1
            if self.nr_copied % SAVE_EVERY == 0:
                source_pool.save()

    def _wait(self, message):
        self.pool.save()
        with self._cond:
            self.phase = 'waiting'
            self.message = message
            self._is_running = False


def read(source, is_listing=True, relpaths=(), from_drive=False):
    """Read source (list it again, if is_listing: a Drive folder anew from Drive if from_drive; and copy
    the files at relpaths); returns its Reading"""
    with _lock:
        reading = _readings.get(source)
        if reading is None:
            reading = _readings[source] = Reading(pools.of(source))
    reading.ask(is_listing, relpaths, from_drive)
    return reading


def _list(source_pool, from_drive):
    """List the source's media files into its pool (a Drive folder's from the Drive cache, read anew
    from Drive first if from_drive). Raises OSError if it can't be read."""
    if not source_pool.is_drive:
        source_pool.add(sources.media_files(source_pool.source))
        return
    if from_drive:
        from dirdelta.drive.clouddirtree import refresh
        try:
            refresh.refresh_cache(paths.path_in_cloud(source_pool.source))
        except Exception as error:
            raise OSError("Couldn't read it from Drive: %s" % (error,))
    source_pool.add(sources.drive_media_files(source_pool.source), is_whole=True)


def _fetch(source_pool, relpath):
    """Copy the file at relpath into the pool (a Drive one downloaded, its SHA-1 Drive's); returns
    its SHA-1. Raises OSError."""
    path = source_pool.local_path(relpath)
    if not source_pool.is_drive:
        return _copy(os.path.join(source_pool.source, relpath), path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    source_pool.tree().fetch_file(relpath, path + '.part')
    os.replace(path + '.part', path)
    with source_pool.lock:
        known = source_pool.files[relpath]['sha1']
    return known or _sha1_of(path)


def _sha1_of(path):
    digest = hashlib.sha1()
    with open(path, 'rb') as found:
        for chunk in iter(lambda: found.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reading_of(source):
    """The source's Reading since the daemon started, or None"""
    with _lock:
        return _readings.get(source)


def copy_one(source_pool, relpath):
    """Copy the file at relpath into the pool now (e.g. as it's moved); returns its SHA-1. Raises
    OSError."""
    sha1 = _fetch(source_pool, relpath)
    source_pool.copied(relpath, sha1)
    return sha1


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
