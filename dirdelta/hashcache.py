"""Local files' contents' hashes, kept in CACHE_FILE (an SQLite database), so a file is read to hash
it once: by its path, with its size and modification time, which say whether it's still the same
file (a hash of a file that changed since isn't given). For a sync's or an inbox sort's comparing of
contents (see elsewhere.py), and for hashing whole replicas in the background (hashing.py). Kept
from any thread.

SQLite rather than a JSON file: a whole replica's hashes (100k files) would be a file rewritten
whole each time it's saved, while a database writes only what changed. What's put is committed at
most every SAVE_INTERVAL seconds (and when dirdelta exits, see save()), so a crash loses at most
that much, which is hashed again next time."""
import atexit
import json
import os
import sqlite3
import threading
import time

CACHE_FILE = os.path.expanduser('~/.cache/dirdelta/hashes.sqlite')
# How often what's put is committed, at most, in seconds (and when dirdelta exits, see save())
SAVE_INTERVAL = 5

_lock = threading.RLock()
# The database (opened at first use), and whether it has what's not committed yet
_db = None
_db_file = None
_is_dirty = False
_last_saved = 0
# The timer that commits what's put, once SAVE_INTERVAL passed, if one is due
_timer = None


def get(path, algorithm):
    """The file's hash by algorithm (a hashlib name), if it's kept and the file hasn't changed since
    (its size and modification time), else None"""
    return get_all(path).get(algorithm)


def get_all(path):
    """{algorithm: hash} of the file's hashes that are kept, if it hasn't changed since (else none)"""
    stamp = _stamp(path)
    if stamp is None:
        return {}
    with _lock:
        db = _database()
        if db is None:
            return {}
        row = db.execute('SELECT size, mtime_ns, hashes FROM files WHERE path = ?', (path,)).fetchone()
    if row is None or list(row[:2]) != stamp:
        return {}
    return json.loads(row[2])


def put(path, hashes, stamp=None):
    """Keep the file's hashes ({algorithm: hex}), as of its size and modification time now (or
    stamp, [size, mtime_ns], what they were when it was read), with the others kept of it then"""
    global _is_dirty
    stamp = stamp or _stamp(path)
    if stamp is None:
        return
    with _lock:
        db = _database()
        if db is None:
            return
        row = db.execute('SELECT size, mtime_ns, hashes FROM files WHERE path = ?', (path,)).fetchone()
        kept = json.loads(row[2]) if row is not None and list(row[:2]) == list(stamp) else {}
        kept.update(hashes)
        db.execute('INSERT OR REPLACE INTO files (path, size, mtime_ns, hashes) VALUES (?, ?, ?, ?)',
                   (path, stamp[0], stamp[1], json.dumps(kept, sort_keys=True)))
        _is_dirty = True
        _save_soon()


def _save_soon():
    """Commit now, if SAVE_INTERVAL passed since the last commit, else once it has (with the lock
    held)"""
    global _timer
    wait = SAVE_INTERVAL - (time.monotonic() - _last_saved)
    if wait <= 0:
        save()
    elif _timer is None:
        _timer = threading.Timer(wait, save)
        # It doesn't keep dirdelta from exiting (which commits, see save())
        _timer.daemon = True
        _timer.start()


def known_under(dirpath):
    """{relpath: (size, mtime_ns, {algorithm: hash})} of the files under dirpath (an absolute path)
    whose hashes are kept, as they were when they were hashed (whether they still are is the
    caller's to tell, e.g. by a find of their sizes and times: one query, rather than one per file)"""
    prefix = dirpath.rstrip('/') + '/'
    with _lock:
        db = _database()
        if db is None:
            return {}
        # The paths starting with prefix: '/' is followed by '0' in the byte order
        rows = db.execute('SELECT path, size, mtime_ns, hashes FROM files WHERE path >= ? AND path < ?',
                          (prefix, prefix[:-1] + '0')).fetchall()
    return {path[len(prefix):]: (size, mtime_ns, json.loads(hashes)) for path, size, mtime_ns, hashes in rows}


def count_under(dirpath):
    """How many files under dirpath (an absolute path) have hashes kept (as they were when hashed)"""
    prefix = dirpath.rstrip('/') + '/'
    with _lock:
        db = _database()
        if db is None:
            return 0
        return db.execute('SELECT count(*) FROM files WHERE path >= ? AND path < ?',
                          (prefix, prefix[:-1] + '0')).fetchone()[0]


def move(path, new_path):
    """A file, or a dir with all in it, was moved from path to new_path (a rename keeps its contents,
    size and modification time): its hashes are kept under its new path"""
    global _is_dirty
    with _lock:
        db = _database()
        if db is None:
            return
        db.execute('UPDATE OR REPLACE files SET path = ? WHERE path = ?', (new_path, path))
        prefix, new_prefix = path.rstrip('/') + '/', new_path.rstrip('/') + '/'
        db.execute('UPDATE OR REPLACE files SET path = ? || substr(path, ?) WHERE path >= ? AND path < ?',
                   (new_prefix, len(prefix) + 1, prefix, prefix[:-1] + '0'))
        _is_dirty = True
        _save_soon()


def save():
    """Commit what was put, if anything"""
    global _is_dirty, _last_saved, _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        if _is_dirty and _db is not None:
            try:
                _db.commit()
            except sqlite3.Error:
                # Only a cache: the hashes are worked out again next time
                pass
        _is_dirty = False
        _last_saved = time.monotonic()


atexit.register(save)


def _database():
    """The database at CACHE_FILE, opened (and made) at first use, or again if CACHE_FILE changed
    (the tests point it elsewhere); None if it can't be (only a cache: nothing is kept then)"""
    global _db, _db_file
    if _db is not None and _db_file == CACHE_FILE:
        return _db
    if _db is not None:
        save()
        _db.close()
        _db = None
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        db = sqlite3.connect(CACHE_FILE, check_same_thread=False)
        # Writes go to a log first, so a crash never leaves it half written
        db.execute('PRAGMA journal_mode=WAL')
        # Only a cache: a commit needn't wait for the disk (a crash may lose the last ones)
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, '
                   'mtime_ns INTEGER, hashes TEXT)')
        db.commit()
    except (OSError, sqlite3.Error):
        return None
    _db, _db_file = db, CACHE_FILE
    return _db


def _stamp(path):
    """What says the file is the same: its size and modification time (ns), or None if it's gone"""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]
