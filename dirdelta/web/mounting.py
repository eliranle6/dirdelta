"""Mounting a local replica's disk from the web page (routes()): the command the terminal would run
(mounts.mount_command()), with sudo given the password the page asked for if it needs one (sudo -S, on its
stdin: never kept, logged or said back), or none if sudo lets the user run it without one (a sudoers rule).

The page asks for the password in a dialog that warns that it crosses the network unencrypted (the web version
is plain HTTP). Mounting changes the system, not files: it's done in a dry run too, as the terminal does."""
import shlex
import subprocess

from dirdelta.known import mounts
from dirdelta.known import replicas
from dirdelta.known.mounts.names import UNCLEAN_NTFS_ERRORS
from dirdelta.trees import paths

# How long a mount may take (ntfs-3g looking over a big volume)
TIMEOUT = 120
# What sudo says when it needs a password it wasn't given (sudo -n), and when the one given was wrong
NEEDS_PASSWORD = 'password is required'
WRONG_PASSWORD = ('incorrect password', 'sorry, try again', 'no password was provided')


def _run(command, password=None):
    """Run command, password (if any) on its stdin; None if it succeeded, else what it said"""
    try:
        result = subprocess.run(command, input='' if password is None else password + '\n', stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, universal_newlines=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    return None if result.returncode == 0 else result.stdout.strip() or "exit code %d" % (result.returncode,)


def mount(path, password=None):
    """Mount the volume the local replica at path was on, where it was. Returns {'ok': True} (with 'readOnly', why,
    if it came up read-only); {'ok': False, 'needsPassword': True, 'command'} if sudo needs a password not given (and
    'error' if the one given was wrong); or {'ok': False, 'error'}"""
    volume = mounts.unmounted(path)
    if volume is None:
        return {'ok': True}
    if not mounts.is_connected(volume):
        return {'ok': False, 'error': "Its disk isn't connected: plug it in first."}
    command = mounts.mount_command(volume)
    plain = command[1:] if command[0] == 'sudo' else command
    if password is None:
        # (Without sudo first if the command needs none (fstab lets users mount it, or udisksctl); it may still need
        # root, e.g. ntfs-3g can't open the device as the user)
        error = _run(plain) if command[0] != 'sudo' else None
        if command[0] == 'sudo' or error is not None:
            error = _run(['sudo', '-n'] + plain)
        if error is not None and NEEDS_PASSWORD in error.lower():
            return {'ok': False, 'needsPassword': True, 'command': shlex.join(['sudo'] + plain)}
    else:
        error = _run(['sudo', '-S', '-k', '-p', ''] + plain, password)
        if error is not None and any(wrong in error.lower() for wrong in WRONG_PASSWORD):
            return {'ok': False, 'needsPassword': True, 'command': shlex.join(['sudo'] + plain),
                    'error': "That password isn't right."}
    if error is not None:
        return {'ok': False, 'error': _said(error)}
    if mounts.unmounted(path) is not None:
        return {'ok': False, 'error': "It said it mounted it, but it isn't mounted."}
    return {'ok': True, 'readOnly': mounts.read_only_lines_of(path)}


def _said(error):
    """What the mount said, and what to do if NTFS wouldn't mount read-write because Windows hibernated"""
    if any(unclean in error.lower() for unclean in UNCLEAN_NTFS_ERRORS):
        error += ("\n\nWindows didn't shut down fully (it hibernated, or Fast Startup is on), so the partition can't "
                  "be mounted read-write. Start Windows and shut it down fully (hold Shift when choosing Shut down, or "
                  "turn Fast Startup off), then try again.")
    return error


def routes():
    def mount_replica(query, body):
        """Mount the disk of the local replica body['path'], sudo given body['password'] if it's there"""
        path = body.get('path', '')
        if path not in replicas.load().replica_paths() or paths.is_cloud_path(path):
            return {'ok': False, 'error': "That's not one of your replicas on this computer."}
        password = body.get('password')
        return mount(path, password if isinstance(password, str) and password else None)

    return {('POST', '/api/replicas/mount'): mount_replica}
