"""When each folder's list was last read from Drive, and uploaded to it; and whose Drive it is"""
import json
import os
import time

from dirdelta.drive.drivecache import names
from dirdelta.drive.drivecache.changes import clean_path
from dirdelta.drive.drivecache.reading import is_at_or_under


def _times_path():
    # Next to the cache (wherever it is, e.g. in tests)
    return os.path.splitext(names.LINES_FILE)[0] + '.times'


def _times():
    """What's kept of when the cache's folders were updated: {'updated': {folder path: when (seconds
    since the epoch) the cache's list of what's under it was last made as Drive has it (read, or
    changed by dirdelta)}, 'uploaded': {folder path: {'modified': the modifiedTime of the copy of
    it last uploaded to Drive, or used from there (see drivemeta.py), 'as_of': the cache's updated()
    of it then}}}"""
    try:
        with open(_times_path()) as times_file:
            times = json.load(times_file)
        if isinstance(times, dict):
            return {'updated': dict(times.get('updated') or {}), 'uploaded': dict(times.get('uploaded') or {}),
                    'user': times.get('user')}
    except (OSError, ValueError):
        pass
    return {'updated': {}, 'uploaded': {}, 'user': None}


def _save_times(times):
    tmp_path = _times_path() + '.tmp'
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, 'w') as times_file:
        json.dump(times, times_file, indent=1)
    os.replace(tmp_path, _times_path())


def note_user(name):
    """Note the Drive account's user name, to say it on the screens"""
    times = _times()
    times['user'] = name
    _save_times(times)


def user():
    """The Drive account's user name, if it's known"""
    return _times()['user']


def note_updated(folder_path, when=None):
    """Note that the cache has what's under folder_path (a path in Drive) as Drive had it at when
    (seconds since the epoch; default: now): read anew, or changed by dirdelta"""
    times = _times()
    times['updated'][clean_path(folder_path)] = time.time() if when is None else when
    _save_times(times)


def updated(folder_path):
    """When the cache's list of folder_path was last updated (see note_updated()), by the latest of
    its own, a folder's above it (read with it) or under it (a change in it): seconds since the
    epoch, or None if it's not known"""
    folder_path = clean_path(folder_path)
    found = [when for path, when in _times()['updated'].items()
             if is_at_or_under(path, folder_path) or is_at_or_under(folder_path, path)]
    return max(found) if found else None


def note_uploaded(folder_path, modified, as_of):
    """Note that the copy of folder_path's list in Drive (see drivemeta.py) has Drive's modifiedTime
    modified, the one this cache made (or used), when the cache's list was updated as of as_of (see
    updated())"""
    times = _times()
    times['uploaded'][clean_path(folder_path)] = {'modified': modified, 'as_of': as_of}
    _save_times(times)


def uploaded(folder_path):
    """What note_uploaded() noted of folder_path: {'modified': ..., 'as_of': ...}, or None"""
    found = _times()['uploaded'].get(clean_path(folder_path))
    return found if isinstance(found, dict) else None
