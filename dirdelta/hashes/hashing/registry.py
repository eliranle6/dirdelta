"""The jobs, one by replica"""
import os
import threading

from dirdelta.hashes.hashing.job import Job
from dirdelta.hashes.hashing.states import NOT_SCANNED


# The jobs, by their replicas' roots
_jobs = {}
_jobs_lock = threading.Lock()


def job(root, max_depth=None):
    """The job of the local replica at root, made if there's none yet (not scanned). There's one for
    a replica, so it goes as deep as the deepest asked for (e.g. a sort, with no limit, after a sync
    of it): if that's deeper now, it's scanned again, if it was."""
    root = os.path.realpath(root)
    with _jobs_lock:
        if root not in _jobs:
            _jobs[root] = Job(root, max_depth)
            return _jobs[root]
        found = _jobs[root]
        is_deeper = found.max_depth is not None and (max_depth is None or max_depth > found.max_depth)
        if is_deeper:
            found.max_depth = max_depth
    if is_deeper and found.progress().state != NOT_SCANNED:
        found.scan_in_background()
    return found


def job_for(root):
    """The job of the local replica at root, if there's one, else None"""
    return _jobs.get(os.path.realpath(root))


def jobs():
    """All the jobs, in the order they were made"""
    with _jobs_lock:
        return list(_jobs.values())
