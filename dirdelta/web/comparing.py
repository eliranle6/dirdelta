"""Comparing pairs of replicas again, in the background (the Replicas page's Compare again, start()): each side's file
list read anew (a local one's from its disk, a Drive one's from Drive), then what each has that the other lacks, by
path, as a sync's menu finds it, noted as the pair's comparison (Replicas.note_compared()), so its status is as they
are now, without a sync being opened. One pair at a time; nothing is copied or changed in the replicas."""
import datetime
import os
import threading

from dirdelta.drive import clouddirtree
from dirdelta.drive import driveapi
from dirdelta.known import mounts
from dirdelta.known import replicas
from dirdelta.known import users
from dirdelta.sync import replica_ops
from dirdelta.trees import localdiskdirtree
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.ui.picker import updates

_lock = threading.Lock()
# {(user, path_a, path_b): what it's doing: 'waiting', 'reading NAME', 'comparing', or the error it stopped at}
_state = {}
_queue = []
_worker = None


def state(user):
    """[{'a', 'b', 'doing', 'error'}] of the user's pairs being compared (or waiting to be), or that failed last"""
    with _lock:
        return [{'a': a, 'b': b, 'doing': doing.get('doing'), 'error': doing.get('error')}
                for (whose, a, b), doing in _state.items() if whose == user]


def start(user, pairs):
    """Compare each of pairs ([(path_a, path_b)], the user's) again, in the background, after the ones asked before;
    one being compared, or waiting, already isn't asked twice"""
    global _worker
    with _lock:
        for a, b in pairs:
            key = (user, a, b)
            if _state.get(key, {}).get('doing'):
                continue
            _state[key] = {'doing': 'waiting'}
            _queue.append(key)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name='comparing')
            _worker.start()


def _work():
    while True:
        with _lock:
            if not _queue:
                return
            key = _queue.pop(0)
        try:
            with messages.quiet():
                _compare(*key)
            with _lock:
                _state.pop(key, None)
        except Exception as error:
            updates.log_error()
            with _lock:
                _state[key] = {'doing': None, 'error': str(error) or error.__class__.__name__}


def _doing(key, what):
    with _lock:
        _state[key] = {'doing': what}


def _compare(user, path_a, path_b):
    key = (user, path_a, path_b)
    trees = []
    for path in (path_a, path_b):
        _doing(key, 'reading ' + path)
        trees.append(_tree(path))
    _doing(key, 'comparing')
    only_a = replica_ops.find_missing(trees[0], trees[1]).relpaths
    only_b = replica_ops.find_missing(trees[1], trees[0]).relpaths
    totals = [sum(1 for entry in tree.iter_files() if not paths.is_meta(entry.relpath)) for tree in trees]
    with users.acting_as(user):
        known = replicas.load()
        known.note_compared(path_a, path_b, len(only_a), len(only_b), when=datetime.datetime.now(), totals=totals)
        replicas.save(known)


def _tree(path):
    """The replica's tree, its file list read anew; raises (saying why) if it can't be"""
    if paths.is_cloud_path(path):
        if not driveapi.can_log_in_quietly():
            raise RuntimeError("not signed in to Google Drive (a sync signs in)")
        clouddirtree.refresh_cache(paths.path_in_cloud(path))
        return clouddirtree.factory(path)
    if mounts.unmounted(path) is not None or not os.path.isdir(path):
        raise RuntimeError("its disk isn't mounted")
    return localdiskdirtree.factory(path, silent=True)
