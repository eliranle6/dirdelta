"""What to call a replica on the screens, telling which disk or Drive account it's on, as the
user labeled it if they did (kept in replicas.REPLICAS_FILE, see Replicas.labels), by what doesn't
change when a path does: each replica's its own, by its identity() (a local one's disk's UUID and its
path there, wherever it's mounted; a Drive one's account and path). Shows nothing, and
asks nothing of Drive: see label_screen.py, and drivemeta.check() for the account's user name."""
import os

from dirdelta import drivecache
from dirdelta import mounts
from dirdelta import paths
from dirdelta import replicas

# How many of the end of a disk's id tell it from the others on a screen
SHORT_ID_LENGTH = 3
LOCAL_DISK = 'LocalDisk'
CLOUD = 'Cloud'

# What was read: each local path's disk's UUID and identity (a process's disks stay as they are, but
# see forget()) and the labels, and the file's state when they were read
_uuids = {}
_identities = {}
_labels = {}
_labels_of = None


def forget():
    """Read the disks anew (e.g. after one was mounted)"""
    _uuids.clear()
    _identities.clear()


def identity(path):
    """The identity of the replica at path, a string, whatever path it's at now: a Drive one's by the
    account and its path, a local one's by the filesystem's UUID and its path in it, or if it has
    none, by its path"""
    if paths.is_cloud_path(path):
        return 'drive:%s:/%s' % (drivecache.root_id() or '?', '/'.join(paths.components(path)[1:]))
    path = os.path.realpath(path)
    mount = mounts.current_mount(path)
    if mount is not None and mount.uuid:
        relpath = os.path.relpath(path, mount.target)
        return 'uuid:%s:/%s' % (mount.uuid, '' if relpath == '.' else relpath)
    return 'path:%s' % (path,)


def _uuid(path):
    """The UUID of the filesystem the local path is on, or None"""
    if path not in _uuids:
        mount = mounts.current_mount(os.path.realpath(path))
        _uuids[path] = mount.uuid if mount is not None else None
    return _uuids[path]


def label_key(path):
    """What the label of the replica at path is kept by: its identity"""
    if paths.is_cloud_path(path):
        return identity(path)
    if path not in _identities:
        _identities[path] = identity(path)
    return _identities[path]


def labels():
    """{label_key(): label}, as the file has them now"""
    global _labels, _labels_of
    try:
        status = os.stat(replicas.REPLICAS_FILE)
        state = (replicas.REPLICAS_FILE, status.st_mtime_ns, status.st_size)
    except OSError:
        return {}
    if state != _labels_of:
        try:
            _labels = replicas.load().labels
        except replicas.ReplicasError:
            _labels = {}
        _labels_of = state
    return _labels


def label(path):
    """The label of the replica at path, or None"""
    found = labels()
    return found.get(label_key(path)) if found else None


def disk_name(path):
    """What to call what a local path is on, without a label: LocalDisk(ABC), by the end of its
    filesystem's UUID, or LocalDisk if it has none; for a Drive path, Cloud(user), by the account's
    user name, if it's known"""
    if paths.is_cloud_path(path):
        user = drivecache.user()
        return '%s(%s)' % (CLOUD, user) if user else CLOUD
    uuid = _uuid(path)
    return '%s(%s)' % (LOCAL_DISK, uuid[-SHORT_ID_LENGTH:]) if uuid else LOCAL_DISK


def full(path):
    """What to call the replica at path to tell it from all others: its label, or what it's on,
    and a local one's path, e.g. LocalDisk(ABC):/mnt/eliran, blue WD:/mnt/eliran, Cloud(me):/eliran"""
    named = label(path)
    if paths.is_cloud_path(path):
        return named or '%s:/%s' % (disk_name(path), '/'.join(paths.components(path)[1:]))
    return '%s:%s' % (named or disk_name(path), path)


def labeled(path):
    """path, after its label if it has one (a Drive one: its label alone), else as it is (where
    the paths are what's listed, e.g. the start menu's)"""
    named = label(path)
    if not named:
        return path
    return named if paths.is_cloud_path(path) else '%s:%s' % (named, path)


def short_names(replica_paths):
    """{path: a short name for it on the screens}: paths.short_names()'s, after a local one's label,
    if it has one (a Drive one: its label)"""
    names = paths.short_names(replica_paths)
    found = labels()
    if not found:
        return names
    for path in names:
        named = found.get(label_key(path))
        if named:
            names[path] = named if paths.is_cloud_path(path) else '%s:%s' % (named, names[path])
    return names
