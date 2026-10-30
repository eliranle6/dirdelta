"""The volumes that local replicas are on, kept in MOUNTS_FILE (JSON) so that one that isn't mounted
now (a disk's partition mounted by hand, an external disk) is found before it's scanned, and can be
mounted again where it was.

An unmounted mount point is still a dir, an empty one on the root filesystem: scanning it would say
that every file is missing, and a live Copy would fill the root filesystem rather than the volume.
So before a replica is used, the recorded mount it's under is checked, and if it isn't mounted the
user is asked whether to mount it (by its UUID, the device's name may differ next time), at the same
mount point, so the replica's path still holds. Mounting changes the system, not files, so it's
asked even in a dry run, and never done without asking."""
import collections
import json
import os
import shlex
import subprocess

from dirdelta import dryrun
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker

MOUNTS_FILE = os.path.expanduser('~/.config/dirdelta/mounts.json')
# Where a connected disk's partitions are, by their filesystems' UUIDs
BY_UUID_DIR = '/dev/disk/by-uuid'
# What ntfs-3g says when Windows hibernated, or shut down with Fast Startup on: it won't mount it
# read-write
UNCLEAN_NTFS_ERRORS = ('unclean file system', 'hibernated', 'windows cache')

MOUNT = 'Mount it'
TRY_AGAIN = "Try again (once it's connected)"
BACK = 'Back'

# A volume as it was mounted: its mount point, device (as it was named then), filesystem type,
# options (the mount's, e.g. 'rw,relatime', and the filesystem's, e.g. 'uid=1000'), UUID and label
Mount = collections.namedtuple('Mount', ['target', 'source', 'fstype', 'vfs_options', 'fs_options',
                                         'uuid', 'label'])


class MountsError(Exception):
    pass


def load():
    """The mounts in MOUNTS_FILE, by mount point (none if there's no file yet)"""
    try:
        with open(MOUNTS_FILE) as mounts_file:
            content = json.load(mounts_file)
        return {target: Mount(target=target, **fields) for target, fields in content.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError, TypeError) as error:
        raise MountsError("Cannot read %s (fix or remove it): %s" % (MOUNTS_FILE, error))


def save(mounts):
    """Write mounts (by mount point) to MOUNTS_FILE, replacing it at once (so it's never half-written)"""
    content = {target: {field: value for field, value in mount._asdict().items() if field != 'target'}
               for target, mount in sorted(mounts.items())}
    try:
        os.makedirs(os.path.dirname(MOUNTS_FILE), exist_ok=True)
        temp_path = MOUNTS_FILE + '.tmp'
        with open(temp_path, 'w') as mounts_file:
            json.dump(content, mounts_file, indent=2)
            mounts_file.write('\n')
        os.replace(temp_path, MOUNTS_FILE)
    except OSError as error:
        raise MountsError("Cannot write %s: %s" % (MOUNTS_FILE, error))


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
             if target != '/' and (path == target or path.startswith(target.rstrip('/') + '/'))]
    if not under:
        return None
    mount = max(under, key=lambda mount: len(mount.target))
    return None if os.path.ismount(mount.target) else mount


def ensure_mounted(path):
    """Before the local path is used: if the volume it was on last time isn't mounted, ask the user
    whether to mount it (or, if its disk isn't connected, to connect it), until it's mounted or they
    go back. Returns whether it's mounted (or never was a volume of its own)."""
    while True:
        mount = unmounted(path)
        if mount is None:
            return True
        if not is_connected(mount):
            header = "%s isn't mounted, and its disk (%s) isn't connected" % (mount.target, _described(mount))
            if picker.pick_option([TRY_AGAIN, BACK], header=header) != TRY_AGAIN:
                return False
            continue
        command = mount_command(mount)
        header = "%s isn't mounted (last time: %s). Mount it?" % (mount.target, _described(mount))
        mount_option = "%s (runs: %s)" % (MOUNT, shlex.join(command))
        if picker.pick_option([mount_option, BACK], header=header) != mount_option:
            return False
        if not _mount(mount, command):
            # Asked again: it may be fixed meanwhile (e.g. the password mistyped)
            continue


def is_connected(mount):
    return os.path.exists(os.path.join(BY_UUID_DIR, mount.uuid))


def mount_command(mount):
    """The command that mounts mount (a Mount) where it was: by its fstab line if it has one (with
    no sudo if the line lets users mount it), else by its UUID with its type and options,
    read-write"""
    fstab_options = _fstab_options(mount.target)
    if fstab_options is not None:
        users_may = {'user', 'users'} & set(fstab_options.split(','))
        return ([] if users_may else ['sudo']) + ['mount', mount.target]
    command = ['sudo', 'mount']
    if mount.fstype and not mount.fstype.startswith('fuse'):
        command += ['-t', mount.fstype]
    return command + ['-o', ','.join(_options(mount)), 'UUID=' + mount.uuid, mount.target]


def _options(mount):
    """The options to mount mount with again: read-write (even if it was read-only), and its
    filesystem's (e.g. a FAT disk's uid=1000), but none of a FUSE filesystem's, which are FUSE's
    own"""
    options = ['rw']
    if mount.fstype not in ('ntfs', 'ntfs-3g') and not mount.fstype.startswith('fuse'):
        options += [option for option in mount.fs_options.split(',') if option and option not in ('ro', 'rw')]
    return options


def _fstab_options(target):
    """The options of fstab's line for the mount point, or None if it has none"""
    try:
        result = subprocess.run(['findmnt', '--fstab', '-no', 'OPTIONS', '--mountpoint', target],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _mount(mount, command):
    """Run command, which mounts mount (sudo asks for the password on the terminal). Returns whether
    it's mounted; if it isn't, the errors were shown (with what to do, if NTFS refused to mount
    read-write because Windows hibernated)."""
    messages.print_line("Running: %s" % (shlex.join(command),))
    error = _run(command)
    if error is None:
        messages.print_line("Mounted %s." % (mount.target,))
        return True
    lines = ["%s failed:" % (shlex.join(command),)] + error.splitlines()
    if any(unclean in error.lower() for unclean in UNCLEAN_NTFS_ERRORS):
        lines += ["", "Windows didn't shut down fully (it hibernated, or Fast Startup is on), so the "
                  "partition can't be mounted read-write. Start Windows and shut it down fully (hold "
                  "Shift when choosing Shut down, or turn Fast Startup off), then try again."]
    messages.show("Cannot mount %s" % (mount.target,), lines, dryrun.label(), 'red')
    return False


def _run(command):
    """Run command, with the terminal as its stdin (for sudo's password). Returns None if it
    succeeded, else what it said (or why it couldn't run)."""
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True)
    except OSError as error:
        return str(error)
    if result.returncode == 0:
        return None
    return result.stdout.strip() or "exit code %d" % (result.returncode,)


def _described(mount):
    """What the user may know the volume by: its device then, type and label"""
    return ', '.join([mount.source or 'UUID ' + mount.uuid, mount.fstype] +
                     (["'%s'" % (mount.label,)] if mount.label else []))
