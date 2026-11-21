"""What a local replica does on the disk itself: the trash, and renames that never overwrite"""
import errno
import os
import shutil
import stat
import subprocess


# What a replacing copy is named next to the file it replaces, until it does (see _replace_file())
PART_PREFIX = '.dirdelta-part.'


def trash(path):
    """Move the file (or dir, with all in it) at path to the desktop's trash (gio trash), where it can be restored
    from, if its drive has one (see has_trash()); else remove it for good. Returns whether it went to the trash.
    Raises OSError if it can't."""
    if not has_trash(path):
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
        return False
    result = subprocess.run(['gio', 'trash', path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
    if result.returncode != 0:
        raise OSError(result.stdout.strip() or "gio trash failed")
    return True


def has_trash(path):
    """Whether the desktop's trash takes the file (or dir) at path without a trash dir made on its drive
    for it: it's on the drive of the home's trash, or its drive has one already (.Trash-UID or
    .Trash/UID at its top, the user's, as the trash spec says and gio checks). Another drive (e.g. a
    Windows one, mounted) is left alone: its files are removed for good."""
    try:
        device = os.lstat(path).st_dev
        if device == os.stat(_existing(_home_trash())).st_dev:
            return True
        top = _mount_point(path)
    except OSError:
        return False
    uid = os.getuid()
    shared = os.path.join(top, '.Trash')
    return (_is_users_dir(os.path.join(top, '.Trash-%d' % (uid,)), uid) or
            (_is_real_dir(shared) and os.stat(shared).st_mode & stat.S_ISVTX and
             _is_users_dir(os.path.join(shared, str(uid)), uid)))


def _is_real_dir(path):
    return os.path.isdir(path) and not os.path.islink(path)


def _is_users_dir(path, uid):
    """Whether path is a dir (not a link) of the user's, which gio trashes into (one of another's,
    e.g. root's on a Windows drive, it refuses)"""
    return _is_real_dir(path) and os.stat(path).st_uid == uid and os.access(path, os.W_OK)


def _home_trash():
    return os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'Trash')


def _existing(path):
    """path, or its closest ancestor that's there"""
    while not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    return path


def _mount_point(path):
    """The top of the drive (filesystem) that path is on"""
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def rename(path, new_path):
    """Move path to new_path: a rename, or between filesystems (which a rename can't), a copy and a
    removal"""
    try:
        os.rename(path, new_path)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(path, new_path)
