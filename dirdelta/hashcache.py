"""Local files' contents' hashes, kept in CACHE_FILE (JSON), so a file is read to hash it once: by its
path, with its size and modification time, which say whether it's still the same file (a hash of a
file that changed since isn't given). For a sync's or an inbox sort's comparing of contents (see
elsewhere.py). Kept from any thread."""
import atexit
import json
import os
import threading
import time

CACHE_FILE = os.path.expanduser('~/.cache/dirdelta/hashes.json')
# How often the cache is written, at most, in seconds (and when dirdelta exits, see save())
SAVE_INTERVAL = 5

_lock = threading.RLock()
_cache = None
_is_dirty = False
_last_saved = 0


def get(path, algorithm):
    """The file's hash by algorithm (a hashlib name), if it's kept and the file hasn't changed since
    (its size and modification time), else None"""
    with _lock:
        entry = _entries().get(path)
        stamp = _stamp(path)
        if entry is None or stamp is None or entry.get('stamp') != stamp:
            return None
        return entry.get('hashes', {}).get(algorithm)


def put(path, hashes):
    """Keep the file's hashes ({algorithm: hex}), as of its size and modification time now"""
    global _is_dirty
    stamp = _stamp(path)
    if stamp is None:
        return
    with _lock:
        entries = _entries()
        entry = entries.get(path)
        if entry is None or entry.get('stamp') != stamp:
            entry = entries[path] = {'stamp': stamp, 'hashes': {}}
        entry['hashes'].update(hashes)
        _is_dirty = True
        if time.monotonic() - _last_saved >= SAVE_INTERVAL:
            save()


def save():
    """Write what's kept, if anything changed (at once: it's never half written)"""
    global _is_dirty, _last_saved
    with _lock:
        if not _is_dirty:
            return
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            temp_path = CACHE_FILE + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(_cache, f)
            os.replace(temp_path, CACHE_FILE)
        except OSError:
            # Only a cache: the hashes are worked out again next time
            pass
        _is_dirty = False
        _last_saved = time.monotonic()


atexit.register(save)


def _entries():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE) as f:
                _cache = json.load(f)
            if not isinstance(_cache, dict):
                _cache = {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _stamp(path):
    """What says the file is the same: its size and modification time (ns), or None if it's gone"""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]
