"""Reading the user's Drive replicas' and inboxes' file lists again when dirdelta is opened (the start
menu, the web version's pages), once the cache's list of one is over a day old: in the background,
quietly (nothing printed), one folder at a time, a folder once at a time; what goes wrong logged
(errors.log), the cache then as it was"""
import datetime
import os
import threading

from dirdelta.drive import driveapi
from dirdelta.trees import paths

MAX_AGE = datetime.timedelta(days=1)

_lock = threading.Lock()
# The cloud paths being read now, or waiting to be
_reading = set()
# How far each one's reading got: {path: (files and folders read, about how many there are, or None)}
_progress = {}


def reading():
    """[{'path', 'read', 'expected'}]: the cloud paths being read now (or waiting to be: read 0), how many
    of their files and folders were read so far, of about how many (None if not known)"""
    with _lock:
        return [{'path': path, 'read': _progress.get(path, (0, None))[0], 'expected': _progress.get(path, (0, None))[1]}
                for path in sorted(_reading)]


def stale(cloud_paths, now=None):
    """The ones of cloud_paths whose list in the cache is over MAX_AGE old (or not known)"""
    from dirdelta.known import replicainfo
    now = now or datetime.datetime.now()
    found = []
    for path in cloud_paths:
        when = replicainfo.cache_time(path)
        if when is None or now - when > MAX_AGE:
            found.append(path)
    return found


def refresh_stale(all_paths):
    """Read again, in a thread of its own, the cloud ones of all_paths whose list is stale (not the
    ones being read already); none if Drive isn't signed in to. Returns the ones it's reading."""
    if not os.path.exists(driveapi.TOKEN_PATH):
        return []
    with _lock:
        found = [path for path in stale(path for path in dict.fromkeys(all_paths) if paths.is_cloud_path(path))
                 if path not in _reading]
        _reading.update(found)
    if found:
        threading.Thread(target=_read, args=(found,), daemon=True, name='freshening').start()
    return found


def _read(cloud_paths):
    from dirdelta.drive.clouddirtree import refresh
    from dirdelta.ui import messages
    from dirdelta.ui.picker import updates
    if not driveapi.can_log_in_quietly():
        # (Logging in again is the browser's: left to a sync, in front of the user)
        with _lock:
            _reading.difference_update(cloud_paths)
        return
    for path in cloud_paths:
        try:
            with messages.quiet():
                refresh.refresh_cache(paths.path_in_cloud(path), lambda read, expected, path=path: _note(path, read, expected))
        except Exception:
            updates.log_error()
        finally:
            with _lock:
                _reading.discard(path)
                _progress.pop(path, None)


def _note(path, read, expected):
    with _lock:
        _progress[path] = (read, expected)
