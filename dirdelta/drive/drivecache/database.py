"""The cache's SQLite database: one connection, from any thread; and importing the old file"""
import atexit
import collections
import contextlib
import json
import os
import sqlite3
import threading

from dirdelta.drive.drivecache import names
from dirdelta.drive.drivecache.metadata import DriveCacheError
from dirdelta.drive.drivecache.names import ROOT_ID_KEY, TRASHED_ID_KEY


def database_path():
    # Next to the cache's old file (wherever it is, e.g. in tests)
    return os.path.splitext(names.LINES_FILE)[0] + '.sqlite'


def exists():
    """Whether there's a cache at all (its old file, not imported yet, is one)"""
    return os.path.exists(database_path()) or os.path.exists(names.LINES_FILE)


def changed_at():
    """When the cache was last changed (seconds since the epoch), or None if there's none"""
    found = []
    # (In WAL mode, what changed last may be in its WAL file)
    for path in (database_path(), database_path() + '-wal', names.LINES_FILE):
        try:
            found.append(os.path.getmtime(path))
        except OSError:
            pass
    return max(found) if found else None


def rows():
    """The metadata of all the files and folders the cache has, whatever's under what"""
    with opened(is_writing=False) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT md FROM files ORDER BY rowid')]


# Around the database, from any thread; how many times it was changed by this process, for what's
# parsed of it (parsefile()); and the one connection kept open: (its database's path, its inode, how
# many were opened so far, the connection). In WAL mode, kept open, a change takes ~0.2ms rather than
# ~20ms, and it's there even if dirdelta is cut off, though a power cut may lose the last ones.
_lock = threading.RLock()
generations = collections.Counter()
kept_connection = None
_nr_connected = 0


def _connected():
    """The connection to the database, as it is now (opened anew if it's another file now)"""
    global kept_connection, _nr_connected
    path = database_path()
    try:
        inode = os.stat(path).st_ino
    except OSError:
        inode = None
    if kept_connection is not None and kept_connection[:2] == (path, inode):
        return kept_connection[3]
    close()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, parent TEXT, md TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS files_by_parent ON files (parent)')
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
    except sqlite3.Error:
        db.close()
        raise
    _nr_connected += 1
    kept_connection = (path, os.stat(path).st_ino, _nr_connected, db)
    return db


def close():
    """Close the connection, if there's one (its WAL file goes into the database then)"""
    global kept_connection
    with _lock:
        if kept_connection is not None:
            connection, kept_connection = kept_connection, None
            connection[3].close()


atexit.register(close)


@contextlib.contextmanager
def opened(is_writing=True):
    """The database (a connection, committing as it ends, all or nothing), its old file imported into
    it first, if it's there. Raises DriveCacheError if it can't be read."""
    with _lock:
        try:
            db = _connected()
            with db:
                is_imported = _import_old_file(db)
                yield db
            # Only once it's in (cut off before, it's imported next time)
            if is_imported:
                os.replace(names.LINES_FILE, names.LINES_FILE + '.bak')
                generations[database_path()] += 1
        except sqlite3.DatabaseError as error:
            close()
            raise DriveCacheError("The cloud files list cache can't be read (%s): remove %s, then run dirdelta "
                                  "again and refresh it." % (error, database_path()))
        if is_writing:
            generations[database_path()] += 1


def put_row(db, md):
    parents = md.get('parents')
    db.execute('INSERT OR REPLACE INTO files (id, parent, md) VALUES (?, ?, ?)',
               (md['id'], parents[0] if parents else None, json.dumps(md)))


def set_root(db, root_id_):
    db.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (ROOT_ID_KEY, root_id_))


def root_of(db):
    row = db.execute('SELECT value FROM meta WHERE key = ?', (ROOT_ID_KEY,)).fetchone()
    return row[0] if row else None


def _import_old_file(db):
    """Take in the cache's old file, if it's there, in the transaction that's open. Returns whether
    it did."""
    if not os.path.exists(names.LINES_FILE):
        return False
    with open(names.LINES_FILE) as old:
        for line in old:
            # Skip non-dict lines
            if not line.startswith('{'):
                continue
            md = json.loads(line)
            if ROOT_ID_KEY in md:
                set_root(db, md[ROOT_ID_KEY])
            elif TRASHED_ID_KEY in md:
                db.execute('DELETE FROM files WHERE id = ?', (md[TRASHED_ID_KEY],))
            else:
                put_row(db, md)
    return True
