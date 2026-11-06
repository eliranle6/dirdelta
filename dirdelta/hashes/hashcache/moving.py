"""A moved file's or dir's hashes, moved with it"""
from dirdelta.hashes.hashcache.database import _dirty, _lock, _save_soon
from dirdelta.hashes.hashcache.replica_dbs import _where


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
