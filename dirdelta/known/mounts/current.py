"""What's mounted now, and remembering it"""
import json
import os
import subprocess

from dirdelta.known.mounts.file import load, save
from dirdelta.known.mounts.names import Mount
from dirdelta.trees import paths


def remember(path):
    """Keep how the volume that the local path is on is mounted, unless it's the root filesystem's
    (nothing to remember) or has no UUID (e.g. a tmpfs, or WSL's Windows drives: not mountable by
    one), or it's kept already"""
    if paths.is_cloud_path(path):
        return
    mount = current_mount(path)
    if mount is None or mount.target == '/' or not mount.uuid:
        return
    mounts = load()
    if mounts.get(mount.target) != mount:
        mounts[mount.target] = mount
        save(mounts)


def current_mount(path):
    """The Mount that the local path is on now (findmnt's), or None if findmnt can't tell"""
    try:
        result = subprocess.run(['findmnt', '-J', '-o', 'TARGET,SOURCE,FSTYPE,VFS-OPTIONS,FS-OPTIONS,UUID,LABEL',
                                 '--target', os.path.realpath(path)],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
        found = json.loads(result.stdout)['filesystems'][0] if result.returncode == 0 else None
    except (OSError, ValueError, KeyError, IndexError):
        return None
    if found is None:
        return None
    fstype = found.get('fstype') or ''
    if fstype.startswith('fuse'):
        # A FUSE filesystem (ntfs-3g's is 'fuseblk') is mounted by its device's type ('ntfs')
        fstype = _device_fstype(found.get('source')) or fstype
    return Mount(found.get('target'), found.get('source'), fstype, found.get('vfs-options') or '',
                 found.get('fs-options') or '', found.get('uuid'), found.get('label'))


def _device_fstype(device):
    try:
        result = subprocess.run(['lsblk', '-dno', 'FSTYPE', device], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, universal_newlines=True)
    except (OSError, TypeError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def unmounted(path):
    """The kept Mount that the local path is under (the innermost), if it isn't mounted now; else
    None (it is, or none is kept)"""
    if paths.is_cloud_path(path):
        return None
    path = os.path.realpath(path)
    under = [mount for target, mount in load().items()
             if target != '/' and paths.is_at_or_under(path, target)]
    if not under:
        return None
    mount = max(under, key=lambda mount: len(mount.target))
    return None if os.path.ismount(mount.target) else mount
