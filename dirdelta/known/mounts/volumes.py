"""Where a local replica is now, by its identity (a disk's UUID and its path on it, replicanames.identity()), not by
the path it was last seen at: two disks of one model (the same label, e.g. "My Passport") are mounted at the same
mount point, so a path alone can't tell which one is meant. The user's replicas' file keeps local replicas by their
identities (replicas.py), and each is at:
- its path on its disk, where the disk is mounted now (several mounted at once: each at its own mount point), or
- if its disk isn't mounted, a placeholder (placeholder()) under PLACEHOLDERS_DIR, by its UUID, which is never made:
  the replica isn't there, until its disk is mounted (mounts.ensure_mounted() mounts it, by its UUID; present() is
  then its real path).

What's mounted is read from MOUNTS_TABLE and BY_UUID_DIR (cheap, so it's read anew each time: a disk is swapped for
another at any time)."""
import os

from dirdelta.known.mounts import names

# Never a dir: a replica whose disk isn't mounted is said to be at PLACEHOLDERS_DIR/UUID/its path on the disk
PLACEHOLDERS_DIR = os.path.expanduser('~/.local/share/dirdelta/not-mounted')


def placeholder(uuid, relpath):
    """The path of the replica at relpath on the disk uuid while that disk isn't mounted"""
    relpath = relpath.strip('/')
    return os.path.join(PLACEHOLDERS_DIR, uuid, relpath) if relpath else os.path.join(PLACEHOLDERS_DIR, uuid)


def of_placeholder(path):
    """(uuid, relpath on the disk) if path is a placeholder() (or a path under one), else None"""
    prefix = PLACEHOLDERS_DIR + '/'
    if not isinstance(path, str) or not path.startswith(prefix):
        return None
    uuid, _, relpath = path[len(prefix):].partition('/')
    return (uuid, relpath) if uuid else None


def mounted():
    """{UUID: its mount point} of the disks mounted now (the first, if one is mounted at several)"""
    devices = {}
    try:
        for uuid in os.listdir(names.BY_UUID_DIR):
            devices.setdefault(os.path.realpath(os.path.join(names.BY_UUID_DIR, uuid)), uuid)
    except OSError:
        return {}
    found = {}
    for device, target in _table():
        uuid = devices.get(os.path.realpath(device)) if device.startswith('/') else None
        if uuid:
            found.setdefault(uuid, target)
    return found


def signature():
    """What's mounted now, as a string that changes whenever it does (to know a cache of disks went stale)"""
    try:
        with open(names.MOUNTS_TABLE) as table:
            return table.read()
    except OSError:
        return ''


def _table():
    """[(device, mount point)] of MOUNTS_TABLE"""
    rows = []
    for line in signature().splitlines():
        fields = line.split()
        if len(fields) >= 2:
            rows.append((_unescaped(fields[0]), _unescaped(fields[1])))
    return rows


def _unescaped(field):
    """A mounts table's field as it is (its spaces and such are written as octal escapes: '\\040')"""
    out, i = [], 0
    while i < len(field):
        if field[i] == '\\' and field[i + 1:i + 4].isdigit():
            out.append(chr(int(field[i + 1:i + 4], 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return ''.join(out)


def located(identity, where=None):
    """The path the replica of identity ('uuid:UUID:/relpath', as replicanames.identity()) is at now: on its disk
    where it's mounted, else its placeholder(); None if identity isn't a disk's. where: mounted(), if it was read"""
    if not identity.startswith('uuid:'):
        return None
    uuid, _, relpath = identity[len('uuid:'):].partition(':')
    if not uuid:
        return None
    target = (mounted() if where is None else where).get(uuid)
    if target is None:
        return placeholder(uuid, relpath)
    relpath = relpath.strip('/')
    return os.path.join(target, relpath) if relpath else target


def present(path):
    """A placeholder's real path if its disk is mounted now (e.g. just mounted); any other path as it is"""
    found = of_placeholder(path)
    if found is None:
        return path
    return located('uuid:%s:/%s' % found)
