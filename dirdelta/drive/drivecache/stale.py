"""The folders whose part of the cache may be out of date: a change to them was cut off"""
import contextlib
import os

from dirdelta.drive.drivecache import names
from dirdelta.drive.drivecache.reading import _is_at_or_under


def _stale_marker_path():
    # Next to the cache (wherever it is, e.g. in tests)
    return os.path.splitext(names.LINES_FILE)[0] + '.stale'


def mark_stale(folder_path):
    """Note that dirdelta is changing what's under folder_path (a path in Drive, like /eliran) in
    Drive, so the cache may not have it, until unmark_stale() (once the changes are in the cache) or
    a refresh of it. Returns whether it wasn't marked already."""
    if folder_path in stale_paths():
        return False
    with open(_stale_marker_path(), 'a') as marker:
        marker.write(folder_path + '\n')
    return True


class _Changing(object):
    """What changing() gives: settled says the cache has what was done, even if a Ctrl-C comes"""
    def __init__(self):
        self.settled = False


@contextlib.contextmanager
def changing(folder_path):
    """Around a change dirdelta makes under folder_path in Drive (and adds to the cache): it's marked
    stale (mark_stale()) while it's made, and unmarked after (unless it was marked before): when it
    ends, or fails with an exception (e.g. an HttpError: Drive changed nothing), but not when it's
    cut off by Ctrl-C (Drive may or may not have the change), unless what it gives (a _Changing) was
    made settled first (e.g. the uploads under way were waited for)"""
    is_newly_stale = mark_stale(folder_path)
    changes = _Changing()
    try:
        yield changes
    except KeyboardInterrupt:
        if is_newly_stale and changes.settled:
            unmark_stale(folder_path)
        raise
    except BaseException:
        if is_newly_stale:
            unmark_stale(folder_path)
        raise
    if is_newly_stale:
        unmark_stale(folder_path)


def unmark_stale(folder_path):
    """Undo mark_stale(folder_path)"""
    _keep_stale_paths(lambda path: path != folder_path)


def mark_fresh(folder_path='/'):
    """Note that what's under folder_path (default: all of My Drive) was just read from Drive, so
    the cache has it as it is"""
    _keep_stale_paths(lambda path: not _is_at_or_under(path, folder_path))


def stale_paths():
    """The folders (paths in Drive) the cache may be out of date in: what's under them was being
    changed by dirdelta when it was cut off"""
    if not os.path.exists(_stale_marker_path()):
        return []
    with open(_stale_marker_path()) as marker:
        return marker.read().splitlines()


def _keep_stale_paths(keep):
    paths = [path for path in stale_paths() if keep(path)]
    if paths:
        with open(_stale_marker_path(), 'w') as marker:
            marker.write(''.join(path + '\n' for path in dict.fromkeys(paths)))
    elif os.path.exists(_stale_marker_path()):
        os.remove(_stale_marker_path())
