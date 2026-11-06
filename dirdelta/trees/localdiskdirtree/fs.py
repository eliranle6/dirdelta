"""What a local replica does on the disk itself: the trash, and renames that never overwrite"""
import errno
import os
import shutil
import subprocess


# What a replacing copy is named next to the file it replaces, until it does (see _replace_file())
PART_PREFIX = '.dirdelta-part.'


def _trash(path):
    """Move the file at path to the desktop's trash (gio trash), where it can be restored from.
    Raises OSError if it can't."""
    result = subprocess.run(['gio', 'trash', path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
    if result.returncode != 0:
        raise OSError(result.stdout.strip() or "gio trash failed")


def _rename(path, new_path):
    """Move path to new_path: a rename, or between filesystems (which a rename can't), a copy and a
    removal"""
    try:
        os.rename(path, new_path)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(path, new_path)
