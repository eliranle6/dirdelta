"""Local files' contents' hashes, kept in SQLite databases, so a file is read to hash it once: by
its path, with its size and modification time, which say whether it's still the same file (a hash
of a file that changed since isn't given). For a sync's or an inbox sort's comparing of contents
(see elsewhere.py), and for hashing whole replicas in the background (hashing.py). Kept from any
thread.

A local replica's files' hashes are kept in it, in META_DIR/META_NAME at its root (by their paths
in it, so they're found wherever its disk is mounted, on any machine), once use_replica() was
called for it: the database is made then (unless it's a dry run, or the replica is read-only), with
the hashes CACHE_FILE had of its files moved into it. Other files' (e.g. an inbox's that isn't in
the sorted tree, or a read-only replica's) are kept in CACHE_FILE, by their absolute paths.

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

from dirdelta import dryrun
from dirdelta import paths

CACHE_FILE = os.path.expanduser('~/.cache/dirdelta/hashes.sqlite')
# A replica's own: META_DIR at its root (see paths.META_DIR), with META_NAME in it
META_NAME = 'hashes.sqlite'
# How often what's put is committed, at most, in seconds (and when dirdelta exits, see save())
SAVE_INTERVAL = 5

_lock = threading.RLock()
# The databases open, by their files (CACHE_FILE's, opened at first use, and the replicas')
_dbs = {}
# The ones with what's not committed yet
_dirty = set()
_last_saved = 0
# The timer that commits what's put, once SAVE_INTERVAL passed, if one is due
_timer = None
# {a replica's root (a real path): its database's file}, of the replicas whose hashes are kept in
# them (see use_replica())
_replicas = {}


def replica_file(root):
    """Where the hashes of the replica at root are kept in it"""
    return os.path.join(root, paths.META_DIR, META_NAME)


def use_replica(root):
    """Keep the hashes of the files of the local replica at root in it (see the module's doc),
    from now on: in the database there, if there's one, else in one made there, unless it's a dry
    run or root can't be written to. The hashes CACHE_FILE has of its files are moved there.
    Returns the database's file, or None if CACHE_FILE is still used for them."""
    root = os.path.realpath(root)
    file = replica_file(root)
    if not os.path.exists(file):
        if dryrun.DRYRUN or not os.access(root, os.W_OK):
            return None
        try:
            os.makedirs(os.path.dirname(file), exist_ok=True)
        except OSError:
            return None
    with _lock:
        db = _open(file)
        if db is None:
            return None
        _replicas[root] = file
        _move_in(root, db)
    return file


def uses_replica(root):
    """The database file of the replica at root, if its hashes are kept in it (else None)"""
    return _replicas.get(os.path.realpath(root))


def _move_in(root, db):
    """Move the hashes CACHE_FILE has of the files under root into db, root's (with the lock held)"""
    central = _database()
    if central is None:
        return
    prefix = root.rstrip('/') + '/'
    rows = central.execute('SELECT path, size, mtime_ns, hashes FROM files WHERE path >= ? AND path < ?',
                           (prefix, prefix[:-1] + '0')).fetchall()
    if not rows:
        return
    db.executemany('INSERT OR IGNORE INTO files (path, size, mtime_ns, hashes) VALUES (?, ?, ?, ?)',
                   [(path[len(prefix):],) + tuple(rest) for path, *rest in rows])
    db.commit()
    central.execute('DELETE FROM files WHERE path >= ? AND path < ?', (prefix, prefix[:-1] + '0'))
    central.commit()


def _where(path):
    """(The database of the file at path (an absolute path), its key there: its path in the replica
    whose it is, or its absolute path in CACHE_FILE's), or (None, None) if none can be opened (with
    the lock held)"""
    for root in sorted(_replicas, key=len, reverse=True):
        if path.startswith(root.rstrip('/') + '/'):
            db = _open(_replicas[root])
            if db is not None:
                return db, path[len(root.rstrip('/')) + 1:]
    db = _database()
    return (db, path) if db is not None else (None, None)


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
        db, key = _where(path)
        if db is None:
            return {}
        row = db.execute('SELECT size, mtime_ns, hashes FROM files WHERE path = ?', (key,)).fetchone()
    if row is None or list(row[:2]) != stamp:
        return {}
    return json.loads(row[2])


def put(path, hashes, stamp=None):
    """Keep the file's hashes ({algorithm: hex}), as of its size and modification time now (or
    stamp, [size, mtime_ns], what they were when it was read), with the others kept of it then"""
    stamp = stamp or _stamp(path)
    if stamp is None:
        return
    with _lock:
        db, key = _where(path)
        if db is None:
            return
        row = db.execute('SELECT size, mtime_ns, hashes FROM files WHERE path = ?', (key,)).fetchone()
        kept = json.loads(row[2]) if row is not None and list(row[:2]) == list(stamp) else {}
        kept.update(hashes)
        db.execute('INSERT OR REPLACE INTO files (path, size, mtime_ns, hashes) VALUES (?, ?, ?, ?)',
                   (key, stamp[0], stamp[1], json.dumps(kept, sort_keys=True)))
        _dirty.add(db)
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


def _rows_under(dirpath):
    """[(relpath under dirpath, size, mtime_ns, hashes' JSON)] of the files under dirpath kept (with
    the lock held)"""
    db, key = _where(dirpath.rstrip('/') + '/')
    if db is None:
        return []
    prefix = key
    if prefix == '':
        # dirpath is a replica's root: all of its database's
        return db.execute('SELECT path, size, mtime_ns, hashes FROM files').fetchall()
    # The paths starting with prefix: '/' is followed by '0' in the byte order
    rows = db.execute('SELECT path, size, mtime_ns, hashes FROM files WHERE path >= ? AND path < ?',
                      (prefix, prefix[:-1] + '0')).fetchall()
    return [(path[len(prefix):],) + tuple(rest) for path, *rest in rows]


def known_under(dirpath):
    """{relpath: (size, mtime_ns, {algorithm: hash})} of the files under dirpath (an absolute path)
    whose hashes are kept, as they were when they were hashed (whether they still are is the
    caller's to tell, e.g. by a find of their sizes and times: one query, rather than one per file)"""
    with _lock:
        rows = _rows_under(dirpath)
    return {relpath: (size, mtime_ns, json.loads(hashes)) for relpath, size, mtime_ns, hashes in rows}


def count_under(dirpath):
    """How many files under dirpath (an absolute path) have hashes kept (as they were when hashed);
    a replica's own database is counted, if it has one, whether or not use_replica() was called"""
    with _lock:
        root = os.path.realpath(dirpath)
        if root not in _replicas and os.path.exists(replica_file(root)):
            db = _open(replica_file(root))
            return db.execute('SELECT count(*) FROM files').fetchone()[0] if db is not None else 0
        return len(_rows_under(dirpath))


def move(path, new_path):
    """A file, or a dir with all in it, was moved from path to new_path (a rename keeps its contents,
    size and modification time): its hashes are kept under its new path"""
    with _lock:
        db, key = _where(path)
        new_db, new_key = _where(new_path)
        if db is None or new_db is None:
            return
        prefix, new_prefix = key.rstrip('/') + '/', new_key.rstrip('/') + '/'
        if db is new_db:
            db.execute('UPDATE OR REPLACE files SET path = ? WHERE path = ?', (new_key, key))
            db.execute('UPDATE OR REPLACE files SET path = ? || substr(path, ?) WHERE path >= ? AND path < ?',
                       (new_prefix, len(prefix) + 1, prefix, prefix[:-1] + '0'))
        else:
            # From one replica's (or CACHE_FILE's) to another's
            rows = db.execute('SELECT path, size, mtime_ns, hashes FROM files WHERE path = ? OR '
                              '(path >= ? AND path < ?)', (key, prefix, prefix[:-1] + '0')).fetchall()
            new_db.executemany('INSERT OR REPLACE INTO files (path, size, mtime_ns, hashes) VALUES (?, ?, ?, ?)',
                               [(new_key if old == key else new_prefix + old[len(prefix):],) + tuple(rest)
                                for old, *rest in rows])
            db.execute('DELETE FROM files WHERE path = ? OR (path >= ? AND path < ?)',
                       (key, prefix, prefix[:-1] + '0'))
            _dirty.add(new_db)
        _dirty.add(db)
        _save_soon()


def save():
    """Commit what was put, if anything"""
    global _last_saved, _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        for db in list(_dirty):
            try:
                db.commit()
            except sqlite3.Error:
                # Only a cache: the hashes are worked out again next time
                pass
        _dirty.clear()
        _last_saved = time.monotonic()


atexit.register(save)


def _database():
    """CACHE_FILE's database, opened (and made) at first use (the tests point CACHE_FILE elsewhere);
    None if it can't be (only a cache: nothing is kept then)"""
    return _open(CACHE_FILE)


def _open(file):
    """The database at file, opened (and made) at first use; None if it can't be (with the lock
    held)"""
    if file in _dbs:
        return _dbs[file]
    try:
        os.makedirs(os.path.dirname(file), exist_ok=True)
        db = sqlite3.connect(file, check_same_thread=False)
        # Writes go to a log first, so a crash never leaves it half written
        db.execute('PRAGMA journal_mode=WAL')
        # Only a cache: a commit needn't wait for the disk (a crash may lose the last ones)
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, '
                   'mtime_ns INTEGER, hashes TEXT)')
        db.commit()
    except (OSError, sqlite3.Error):
        return None
    _dbs[file] = db
    return db


def _stamp(path):
    """What says the file is the same: its size and modification time (ns), or None if it's gone"""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]
