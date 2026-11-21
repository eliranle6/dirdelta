"""The web version's side of the records replicas keep of themselves (known/selfrecords.py): each replica's checked as
the pages list them (status()), its own record read again at most every READ_EVERY seconds (a Drive one's is a request
to Drive), and a disparity settled from its card (routes())"""
import threading
import time

from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.known import selfrecords
from dirdelta.trees import paths
from dirdelta.ui.picker import updates

# How long a replica's record, as read, is taken as it is, in seconds: a local one's, and a Drive one's
READ_EVERY = {False: 5, True: 300}

# {path: (when it was read, the record or None, or the error)}
_read = {}
_lock = threading.Lock()


def forget(path=None):
    """Read the replica's record (or every one's) again next time"""
    with _lock:
        if path is None:
            _read.clear()
        else:
            _read.pop(path, None)


def _record(path):
    """The replica's record, read at most every READ_EVERY seconds: (the record or None, an error's text or '')"""
    now = time.monotonic()
    with _lock:
        found = _read.get(path)
    if found is not None and now - found[0] < READ_EVERY[paths.is_cloud_path(path)]:
        return found[1], found[2]
    try:
        record, error = selfrecords.read(path), ''
    except Exception as failed:
        record, error = None, str(failed) or failed.__class__.__name__
    with _lock:
        _read[path] = (now, record, error)
    return record, error


def status(path, known):
    """What the replica's card says of its record (checking it, see selfrecords.check(); known changed, not saved):
    {'kept': whether it keeps its record, 'why': why not, 'disparity': selfrecords' or None}"""
    record, error = _record(path)
    if error:
        return {'kept': False, 'why': "its record couldn't be read: %s" % (error,), 'disparity': None}
    try:
        found = selfrecords.check(path, known, record)
    except Exception:
        updates.log_error()
        return {'kept': False, 'why': "its record couldn't be checked", 'disparity': None}
    if found.kept and record is None:
        # (Written now: read again next time)
        forget(path)
    return {'kept': found.kept, 'why': found.why, 'disparity': found.disparity}


def statuses(replica_paths, is_there):
    """{path: status()} of the replicas there (is_there(path)), the file saved if checking them changed it"""
    known = replicas.load()
    before = _mine(known)
    found = {path: status(path, known) for path in replica_paths if is_there(path)}
    if _mine(known) != before:
        replicas.save(known)
    return found


def _mine(known):
    return repr((known.labels, known.looks, known.records))


def routes():
    def resolve(query, body):
        """Settle a replica's disparity: body['how'] is selfrecords.TAKE_THEIRS or WRITE_MINE"""
        path, how = body.get('path', ''), body.get('how')
        known = replicas.load()
        if path not in known.replica_paths() or how not in (selfrecords.TAKE_THEIRS, selfrecords.WRITE_MINE):
            return {'ok': False}
        try:
            found = selfrecords.resolve(path, known, how)
        except Exception as error:
            return {'ok': False, 'error': str(error)}
        replicas.save(known)
        forget(path)
        return {'ok': found.kept, 'error': found.why, 'name': replicanames.name(path)}
    return {('POST', '/api/replicas/record'): resolve}
