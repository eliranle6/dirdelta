"""Getting a file's hashes, putting them, and the ones known under a dir"""
import json
import os

from dirdelta.hashes.hashcache.database import _dirty, _lock, _open, _replicas, _save_soon
from dirdelta.hashes.hashcache.replica_dbs import _where, replica_file


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


def _stamp(path):
    """What says the file is the same: its size and modification time (ns), or None if it's gone"""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]
