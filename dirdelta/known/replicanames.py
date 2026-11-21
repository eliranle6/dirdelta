"""What to call a replica on the screens, telling which disk or Drive account it's on, as the
user labeled it if they did (kept in the user's replicas.json, see Replicas.labels), by what doesn't
change when a path does: each replica's its own, by its identity() (a local one's disk's UUID and its
path there, wherever it's mounted; a Drive one's account and path). Shows nothing, and
asks nothing of Drive: see label_screen.py, and drivemeta.check() for the account's user name."""
import os

from dirdelta.drive import drivecache
from dirdelta.known import mounts
from dirdelta.known.mounts import volumes
from dirdelta.trees import paths
from dirdelta.known import replicas

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
_known = []
# What was mounted when the disks were read (volumes.signature())
_mounts_seen = None


def forget():
    """Read the disks anew (e.g. after one was mounted)"""
    _uuids.clear()
    _identities.clear()


def _fresh():
    """The disks read anew if what's mounted changed since they were read (another disk may be at the same mount
    point now: two of one model)"""
    global _mounts_seen
    now = volumes.signature()
    if now != _mounts_seen:
        forget()
        _mounts_seen = now


def identity(path):
    """The identity of the replica at path, a string, whatever path it's at now: a Drive one's by the
    account and its path, a local one's by the filesystem's UUID and its path in it, or if it has
    none, by its path"""
    if paths.is_cloud_path(path):
        return 'drive:%s:/%s' % (drivecache.root_id() or '?', '/'.join(paths.components(path)[1:]))
    # (A replica whose disk isn't mounted: its identity is in its path, see volumes.py)
    on_disk = volumes.of_placeholder(path)
    if on_disk is not None:
        return 'uuid:%s:/%s' % on_disk
    path = os.path.realpath(path)
    mount = _mount_of(path)
    if mount is not None and mount.uuid:
        relpath = os.path.relpath(path, mount.target)
        return 'uuid:%s:/%s' % (mount.uuid, '' if relpath == '.' else relpath)
    return 'path:%s' % (path,)


def _mount_of(path):
    """The mount the local path is on: its disk's as it was kept, if it isn't mounted now (not the disk its
    empty mount point is on), else the one it's on now"""
    return mounts.unmounted(path) or mounts.current_mount(path)


def _uuid(path):
    """The UUID of the filesystem the local path is on, or None"""
    _fresh()
    if path not in _uuids:
        mount = _mount_of(os.path.realpath(path))
        _uuids[path] = mount.uuid if mount is not None else None
    return _uuids[path]


def label_key(path):
    """What the label of the replica at path is kept by: its identity"""
    if paths.is_cloud_path(path):
        return identity(path)
    _fresh()
    if path not in _identities:
        _identities[path] = identity(path)
    return _identities[path]


def labels():
    """{label_key(): label}, as the file has them now"""
    _read()
    return _labels


def _known_paths():
    """The user's replicas' and inboxes' paths, as the file has them now"""
    _read()
    return _known


def _read():
    """The labels and the known paths, read again if the file changed, or what's mounted did (a replica's path is
    where its disk is mounted, or its placeholder while it isn't: volumes.py)"""
    global _labels, _labels_of, _known
    try:
        path = replicas.replicas_file()
        status = os.stat(path)
        state = (path, status.st_mtime_ns, status.st_size, volumes.signature())
    except OSError:
        _labels, _known = {}, []
        return
    if state != _labels_of:
        try:
            found = replicas.load()
            _labels, _known = found.labels, found.replica_paths() + found.inbox_paths()
        except replicas.ReplicasError:
            _labels, _known = {}, []
        _labels_of = state


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
    """What to call the replica at path (its one name, see short_names())"""
    return name(path)


def labeled(path):
    """path, after its label if it has one (a Drive one: its label alone), else as it is (where
    the paths are what's listed, e.g. the start menu's)"""
    named = label(path)
    if not named:
        return path
    return named if paths.is_cloud_path(path) else '%s:%s' % (named, path)


def short_names(replica_paths):
    """{path: its name on every screen}: its label, if the user gave it one; else what it's on, its disk
    (disk_name(): LocalDisk(07B), Cloud(me)); and when another known replica or inbox (or one of
    replica_paths) would be called the same, its folder's name after it (LocalDisk(07B):eliran). Never
    the dirs above it."""
    names = {}
    others = list(dict.fromkeys(list(replica_paths) + [path for path in _known_paths()]))
    base = {path: label(path) or disk_name(path) for path in others}
    for path in replica_paths:
        same = [other for other in others if base[other] == base[path] and not _same_place(other, path)]
        names[path] = base[path] if not same else '%s:%s' % (base[path], _folder_name(path))
    return names


def _same_place(one, other):
    """Whether two paths are one replica's (the same, normalized)"""
    return paths.normalized(one) == paths.normalized(other)


def _folder_name(path):
    """The replica's own folder's name (a Drive one's, or its account's root: /)"""
    if paths.is_cloud_path(path):
        components = paths.components(path)
        return components[-1] if len(components) > 1 else '/'
    return os.path.basename(os.path.realpath(path).rstrip('/')) or '/'


def name(path):
    """The replica's name on every screen (see short_names())"""
    return short_names([path])[path]


def told_apart(replica_paths):
    """{path: its one name} (see short_names(): it tells them apart already)"""
    return short_names(replica_paths)
