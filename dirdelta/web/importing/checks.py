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
from dirdelta.known.mounts import volumes
from dirdelta.phoneimport import known, suggest
from dirdelta.trees import paths
from dirdelta.ui.picker import updates
from dirdelta.web import naming

RECHECK_AFTER = 600
# How long a replica's identity (its disk's, by findmnt) is taken as known, in seconds
IDENTITY_FOR = 5

# {path: (when, its identity)}
_identities = {}
_identities_lock = threading.Lock()


def identity(path):
    """The identity of the replica at path now (replicanames.identity(): by its disk's UUID and the
    path in it, so another disk mounted there is another replica), found again after IDENTITY_FOR"""
    now = time.monotonic()
    with _identities_lock:
        found = _identities.get(path)
    if found is not None and now - found[0] < IDENTITY_FOR:
        return found[1]
    found = replicanames.identity(path)
    with _identities_lock:
        _identities[path] = (now, found)
    return found


class Check(object):
    """A destination's check: known (the last one done, or None), its suggester, when it was done, and
    whether one is being done"""

    def __init__(self, dest, dest_id):
        self.dest, self.dest_id = dest, dest_id
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

    def _of(self, dest):
        """The Check of the replica at dest now (by its identity: another disk there has its own)"""
        dest_id = identity(dest)
        return self._checks.setdefault((dest, dest_id), Check(dest, dest_id))

    def get(self, dest):
        """dest's Check, a new one started if it's due"""
        with self._lock:
            check = self._of(dest)
            if not check.is_checking and (check.known is None or time.time() - check.checked_at > RECHECK_AFTER
                                          or self._hashing_done(check)):
                self._start(check)
            return check

    def recheck(self, dest):
        with self._lock:
            check = self._of(dest)
            if not check.is_checking:
                self._start(check)

    @staticmethod
    def _hashing_done(check):
        done = {root for root in check.hashing if hash_state(root)['state'] == hashing.DONE}
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
            check = self._of(dest)
            check.hashing.add(root)
        dashboard_actions.start_hashing(root)

    def read_drive(self, dest, replica_path):
        """Read the Drive replica at replica_path anew from Drive into the cache, then check again"""
        from dirdelta.drive.clouddirtree import refresh
        with self._lock:
            check = self._of(dest)
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
    found = {'path': root, 'name': naming.name(root),
             'kind': 'drive' if is_cloud else 'local', 'disk': replicanames.disk_name(root), 'reading': root in check.reading,
             'unhashed': check.known.unhashed.get(root, 0) if check.known is not None and not is_cloud else 0}
    if not is_cloud:
        found['hashing'] = hash_state(root)
    return found


def hash_state(root):
    job = hashing.job_for(root)
    if job is None:
        return {'state': None}
    progress = job.progress()
    return {'state': progress.state, 'started': progress.is_started, 'files': progress.nr_files, 'done': progress.nr_done,
            'withMedia': job.with_media, 'leftOut': progress.nr_left_out}


def synced_with(path):
    """The user's other replicas than the one at path (copies of one tree, see replica_lists.py) that can be looked in
    now: a disk that isn't mounted (at its placeholder, see volumes.py) isn't, nor said not to be there"""
    path = paths.normalized(path)
    return [other for other in replicas.load().replica_paths() if other != path and
            (paths.is_cloud_path(other) or (volumes.of_placeholder(other) is None and os.path.isdir(other)))]


def destinations(source=None):
    """[{'path', 'name', 'disk', 'kind'}] of the user's replicas an import of source may go into (any:
    they're copies of one tree), the likeliest first: the one it was last sorted into, then local ones
    that are there (a disk's); for a Drive folder, Drive ones too, after them"""
    known_replicas = replicas.load()
    candidates = [root for inbox, root in known_replicas.sorts if inbox == source] + \
        [path for path in known_replicas.replica_paths() if not paths.is_cloud_path(path)] + known_replicas.replica_paths()
    is_drive = source is not None and paths.is_cloud_path(source)
    found = [path for path in dict.fromkeys(candidates) if path != source and
             (os.path.isdir(path) if not paths.is_cloud_path(path) else is_drive)]
    return [{'path': path, 'name': naming.name(path),
             'disk': replicanames.disk_name(path), 'kind': 'drive' if paths.is_cloud_path(path) else 'local'}
            for path in found]
