"""The databases kept (CACHE_FILE's, and each replica's own), opened once, from any thread, and
committed at most every SAVE_INTERVAL seconds"""
import atexit
import os
import sqlite3
import threading
import time


CACHE_FILE = os.path.expanduser('~/.cache/dirdelta/hashes.sqlite')
# A replica's own: META_DIR at its root (see paths.META_DIR), with META_NAME in it
META_NAME = 'hashes.sqlite'
# How often what's put is committed, at most, in seconds (and when dirdelta exits, see save())
SAVE_INTERVAL = 5

lock = threading.RLock()
# The databases open, by their files (CACHE_FILE's, opened at first use, and the replicas')
_dbs = {}
# The ones with what's not committed yet
dirty = set()
_last_saved = 0
# The timer that commits what's put, once SAVE_INTERVAL passed, if one is due
_timer = None
# {a replica's root (a real path): its database's file}, of the replicas whose hashes are kept in
# them (see use_replica())
replicas = {}


def save_soon():
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


def save():
    """Commit what was put, if anything"""
    global _last_saved, _timer
    with lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        for db in list(dirty):
            try:
                db.commit()
            except sqlite3.Error:
                # Only a cache: the hashes are worked out again next time
                pass
        dirty.clear()
        _last_saved = time.monotonic()


atexit.register(save)


def cache_database():
    """CACHE_FILE's database, opened (and made) at first use (the tests point CACHE_FILE elsewhere);
    None if it can't be (only a cache: nothing is kept then)"""
    return open_database(CACHE_FILE)


def open_database(file):
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
