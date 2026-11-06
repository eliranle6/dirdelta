"""What the file pickers show of hashing: their key, each file's tag, and the status line"""
import os
import threading

from dirdelta.screens.hashes_screen import status as hash_status
from dirdelta.screens.hashes_screen.offering import jobs_of
from dirdelta.ui import picker


# Every menu says how far hashing got, as it goes on behind them
picker.set_ambient_status(lambda: hash_status.status_parts(hash_status.active_jobs()))


class Marks(object):
    """A picker's shown_as (see picker.pick_files()) of a job's files (relpaths, of its replica's):
    each file's name with its tag (hashed, being hashed, not yet; see hash_status.tag()), as it
    changes; and the status, a label of each of status_jobs (see hash_status.status_parts()), and then
    extra() (more parts, [(text, color)]), if given. close() it once the picker is gone."""

    def __init__(self, job, relpaths, status_jobs, extra=None):
        self._job = job
        self._relpaths = relpaths
        self._status_jobs = status_jobs
        self._extra = extra
        self._lock = threading.Lock()
        # The files whose marks may have changed since they were last shown (None: all of them),
        # and the ones being hashed when they were
        self._changed = None
        self._current = set()
        self._wanted = set(relpaths) if job is not None else set()
        if job is not None:
            job.subscribe(self._on_hashed)

    def _on_hashed(self, relpath, hashes):
        if relpath in self._wanted:
            with self._lock:
                if self._changed is not None:
                    self._changed.add(relpath)

    def close(self):
        """No more marks to change"""
        if self._job is not None:
            self._job.unsubscribe(self._on_hashed)

    def text(self, relpath):
        """What the file at relpath is shown as: its name, and its tag if it's the job's"""
        name = os.path.basename(relpath)
        if self._job is None or relpath not in self._wanted:
            return name
        tag = hash_status.tag(self._job, relpath)
        return picker.styled([(name, None), ("  ", None), (tag, hash_status.TAG_STYLES[tag])])

    def __call__(self):
        shown = {}
        if self._job is not None:
            current = set(self._job.progress().current) & self._wanted
            with self._lock:
                changed, self._changed = self._changed, set()
            changed = set(self._relpaths) if changed is None else changed | current | self._current
            self._current = current
            for relpath in changed:
                shown[relpath] = self.text(relpath)
        shown[''] = picker.segments(hash_status.status_parts(self._status_jobs) + (self._extra() if self._extra else []))
        return shown


def picker_status(replicas, extra=()):
    """The status of a picker of replicas (trees) that has no Marks: a label of each local one's job"""
    return picker.segments(hash_status.status_parts(jobs_of(replicas)) + list(extra))
