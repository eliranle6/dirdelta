"""What each import's replicas have (Checks): its destination's and its synced replicas' files (a Known),
read on a thread when first asked for, and again when asked to, when it's older than RECHECK_AFTER, or
when a replica's hashing that was started here is done; meanwhile the one before is used. And what's
done to a replica to compare better: hashing a local one's files, reading a Drive one again."""
import os
import threading
import time

from dirdelta.hashes import hashing
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.phoneimport import known, suggest
from dirdelta.trees import paths
from dirdelta.ui.picker import updates

RECHECK_AFTER = 600


class Check(object):
    """A destination's check: known (the last one done, or None), its suggester, when it was done, and
    whether one is being done"""

    def __init__(self, dest):
        self.dest = dest
        self.known = self.suggester = None
        self.checked_at = None
        self.is_checking = False
        # The local replicas hashed from here, till their hashing's done; Drive ones being read again
        self.hashing = set()
        self.reading = set()
        self.errors = []

    @property
    def replica_paths(self):
        return self.known.replica_paths if self.known is not None else [self.dest] + synced_with(self.dest)


class Checks(object):
    def __init__(self):
        self._checks, self._lock = {}, threading.Lock()

    def get(self, dest):
        """dest's Check, a new one started if it's due"""
        with self._lock:
            check = self._checks.setdefault(dest, Check(dest))
            if not check.is_checking and (check.known is None or time.time() - check.checked_at > RECHECK_AFTER
                                          or self._hashing_done(check)):
                self._start(check)
            return check

    def recheck(self, dest):
        with self._lock:
            check = self._checks.setdefault(dest, Check(dest))
            if not check.is_checking:
                self._start(check)

    @staticmethod
    def _hashing_done(check):
        done = {root for root in check.hashing if _hash_state(root)['state'] == hashing.DONE}
        check.hashing -= done
        return bool(done)

    def _start(self, check):
        check.is_checking = True
        threading.Thread(target=self._check, args=(check,), daemon=True).start()

    def _check(self, check):
        try:
            found = known.Known([check.dest] + synced_with(check.dest))
            found.index()
            suggester = suggest.Suggester(found.media_relpaths(check.dest))
        except Exception:
            updates.log_error()
            found = suggester = None
        with self._lock:
            if found is not None:
                check.known, check.suggester = found, suggester
            check.checked_at = time.time()
            check.is_checking = False

    def hash(self, dest, root):
        """Hash the local replica at root's files (as the replicas dashboard does), and check again once
        that's done"""
        from dirdelta.screens.hashes_screen import dashboard_actions
        with self._lock:
            check = self._checks.setdefault(dest, Check(dest))
            check.hashing.add(root)
        dashboard_actions.start_hashing(root)

    def read_drive(self, dest, replica_path):
        """Read the Drive replica at replica_path anew from Drive into the cache, then check again"""
        from dirdelta.drive.clouddirtree import refresh
        with self._lock:
            check = self._checks.setdefault(dest, Check(dest))
            if replica_path in check.reading:
                return
            check.reading.add(replica_path)

        def run():
            try:
                refresh.refresh_cache(paths.path_in_cloud(replica_path))
            except Exception as error:
                updates.log_error()
                check.errors.append("Couldn't read %s from Drive: %s" % (replica_path, error))
            with self._lock:
                check.reading.discard(replica_path)
            self.recheck(dest)
        threading.Thread(target=run, daemon=True).start()


def replica_state(check, root):
    """What the page says of a replica of check: its name, kind, and what's being done to it"""
    is_cloud = paths.is_cloud_path(root)
    found = {'path': root, 'name': replicanames.label(root) or os.path.basename(root.rstrip('/')) or root,
             'kind': 'drive' if is_cloud else 'local', 'reading': root in check.reading,
             'unhashed': check.known.unhashed.get(root, 0) if check.known is not None and not is_cloud else 0}
    if not is_cloud:
        found['hashing'] = _hash_state(root)
    return found


def _hash_state(root):
    job = hashing.job_for(root)
    if job is None:
        return {'state': None}
    progress = job.progress()
    return {'state': progress.state, 'started': progress.is_started, 'files': progress.nr_files, 'done': progress.nr_done}


def synced_with(path):
    """The replicas the replica at path was synced with (the favorites', the history's)"""
    path = paths.normalized(path)
    known_replicas = replicas.load()
    return list(dict.fromkeys(other for pair in known_replicas.favorites + known_replicas.history if path in pair
                              for other in pair if other != path))


def destinations():
    """The local replicas an import may go into (the sorted trees first), and the default one"""
    known_replicas = replicas.load()
    candidates = [root for _, root in known_replicas.sorts] + [path for pair in known_replicas.favorites +
                                                               known_replicas.history for path in pair]
    local = [path for path in dict.fromkeys(candidates) if not paths.is_cloud_path(path) and os.path.isdir(path)]
    return local, local[0] if local else None
