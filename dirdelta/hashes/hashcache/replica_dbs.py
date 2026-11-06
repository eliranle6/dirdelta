"""A local replica's own database (META_DIR/META_NAME in it), and which database has a file"""
import os

from dirdelta.hashes.hashcache.database import META_NAME, cache_database, lock, open_database, replicas
from dirdelta.trees import paths
from dirdelta.util import dryrun


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
    with lock:
        db = open_database(file)
        if db is None:
            return None
        replicas[root] = file
        _move_in(root, db)
    return file


def uses_replica(root):
    """The database file of the replica at root, if its hashes are kept in it (else None)"""
    return replicas.get(os.path.realpath(root))


def _move_in(root, db):
    """Move the hashes CACHE_FILE has of the files under root into db, root's (with the lock held)"""
    central = cache_database()
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


def where(path):
    """(The database of the file at path (an absolute path), its key there: its path in the replica
    whose it is, or its absolute path in CACHE_FILE's), or (None, None) if none can be opened (with
    the lock held)"""
    for root in sorted(replicas, key=len, reverse=True):
        if path.startswith(root.rstrip('/') + '/'):
            db = open_database(replicas[root])
            if db is not None:
                return db, path[len(root.rstrip('/')) + 1:]
    db = cache_database()
    return (db, path) if db is not None else (None, None)
