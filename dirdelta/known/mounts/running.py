"""Running the commands that say what's mounted, and mount"""
import subprocess


def run_command(command):
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


def described(mount):
    """What the user may know the volume by: its device then, type and label"""
    return ', '.join([mount.source or 'UUID ' + mount.uuid, mount.fstype] +
                     (["'%s'" % (mount.label,)] if mount.label else []))
