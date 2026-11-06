"""Why a volume is read-only, and what to do about it"""
import os

from dirdelta.known.mounts import current
from dirdelta.known.mounts.names import HIBERNATED_MARK, HIBERNATION_FILE
from dirdelta.trees import paths


def _read_only_lines(mount):
    """What to say of mount, which is read-only"""
    lines = ["It's mounted read-only: you can still copy its files to other replicas, but nothing "
             "can be copied into it, removed from it or moved in it."]
    return lines + read_only_reason(mount)


def read_only_reason(mount):
    """Lines saying why mount (a Mount) is read-only, and what to do, as far as it's known"""
    if _is_windows_hibernated(mount):
        return ["", "Windows didn't shut down fully (it hibernated, or Fast Startup is on), which makes writing to it "
                "unsafe. In Windows, turn both off with this, as an Administrator:", "  powercfg /h off",
                "or for once, hold Shift when choosing Shut down. Then unmount it and run dirdelta again."]
    return ["", "It may have been mounted so on purpose (to change that: sudo mount -o remount,rw %s), its filesystem "
            "may have errors, or the disk be write-protected (see sudo dmesg)." % (mount.target,)]


def _is_windows_hibernated(mount):
    """Whether the NTFS volume has Windows' saved session, by the start of its hibernation file"""
    if mount.fstype not in ('ntfs', 'ntfs-3g'):
        return False
    try:
        with open(os.path.join(mount.target, HIBERNATION_FILE), 'rb') as hibernation:
            return hibernation.read(len(HIBERNATED_MARK)).upper() == HIBERNATED_MARK
    except OSError:
        return False


def read_only_lines_of(path):
    """Why the local dir at path is read-only, if it's because its volume is mounted so (none if not,
    e.g. it's only its permissions, or Drive's)"""
    if paths.is_cloud_path(path):
        return []
    mount = current.current_mount(path)
    if mount is None or 'ro' not in mount.vfs_options.split(','):
        return []
    return read_only_reason(mount)
