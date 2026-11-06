"""Mounting a volume again where it was, once the user says so"""
import os
import shlex
import subprocess

from dirdelta.known.mounts import current
from dirdelta.known.mounts import names
from dirdelta.known.mounts.current import unmounted
from dirdelta.known.mounts.names import BACK, MOUNT, TRY_AGAIN, UNCLEAN_NTFS_ERRORS
from dirdelta.known.mounts.read_only import read_only_lines
from dirdelta.known.mounts.running import described, run_command
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


def ensure_mounted(path):
    """Before the local path is used: if the volume it was on last time isn't mounted, ask the user
    whether to mount it (or, if its disk isn't connected, to connect it), until it's mounted or they
    go back. Returns whether it's mounted (or never was a volume of its own)."""
    while True:
        mount = unmounted(path)
        if mount is None:
            return True
        if not is_connected(mount):
            header = "Connect its disk? (for %s)\n\n%s isn't mounted, and its disk (%s) isn't connected." % (
                mount.target, mount.target, described(mount))
            if picker.pick_option([TRY_AGAIN, BACK], header=header, title='Mount') != TRY_AGAIN:
                return False
            continue
        command = mount_command(mount)
        header = "Mount it? (%s)\n\nIt isn't mounted (last time: %s)." % (mount.target, described(mount))
        mount_option = "%s (runs: %s)" % (MOUNT, shlex.join(command))
        if picker.pick_option([mount_option, BACK], header=header, title='Mount') != mount_option:
            return False
        if not _mount(mount, command):
            # Asked again: it may be fixed meanwhile (e.g. the password mistyped)
            continue


def is_connected(mount):
    return os.path.exists(os.path.join(names.BY_UUID_DIR, mount.uuid))


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
    error = run_command(command)
    if error is None:
        messages.print_line("Mounted %s." % (mount.target,))
        if _came_up_read_only(mount):
            messages.show("Mounted read-only: %s" % (mount.target,), read_only_lines(mount), dryrun.label(), 'yellow')
        return True
    lines = ["%s failed:" % (shlex.join(command),)] + error.splitlines()
    if any(unclean in error.lower() for unclean in UNCLEAN_NTFS_ERRORS):
        lines += ["", "Windows didn't shut down fully (it hibernated, or Fast Startup is on), so the "
                  "partition can't be mounted read-write. Start Windows and shut it down fully (hold "
                  "Shift when choosing Shut down, or turn Fast Startup off), then try again."]
    messages.show("Cannot mount %s" % (mount.target,), lines, dryrun.label(), 'red')
    return False


def _came_up_read_only(mount):
    """Whether mount, just mounted, is read-only though it was asked to be read-write (ntfs-3g does
    so, and succeeds, when Windows hibernated), not because fstab's line says it's to be"""
    now = current.current_mount(mount.target)
    if now is None or now.target != mount.target or 'ro' not in now.vfs_options.split(','):
        return False
    return 'ro' not in (_fstab_options(mount.target) or '').split(',')
