"""Where an import's files come from: the phones plugged in (phones(): Android's MTP, mounted by GNOME's
gvfs under GVFS_DIR), or any local dir; and a source's media files (media_files()), wherever they are in
it, since phones keep them differently (DCIM/Camera, Pictures/, WhatsApp's dirs...)"""
import glob
import os

from dirdelta.util import media

GVFS_DIR = '/run/user/%d/gvfs' % (os.getuid(),)
# Dirs not looked in: apps' own data, thumbnails, and the trash
SKIPPED_DIRS = {'.thumbnails', '.trashed', '.Trash', 'Android', '.cache', 'cache', 'LOST.DIR'}


# The dirs of a phone's storage imported from (others may be added: Pictures, WhatsApp's...)
PHONE_DIRS = ('DCIM',)
MTP_PREFIX = 'mtp:host='


def phones():
    """[(name, path)] of the dirs imported from (PHONE_DIRS) of the phones mounted now, e.g. ('Pixel 8',
    '/run/user/1000/gvfs/mtp:host=Google_Pixel_8_.../Internal shared storage/DCIM')"""
    found = []
    for mount in sorted(glob.glob(os.path.join(GVFS_DIR, MTP_PREFIX + '*'))):
        try:
            storages = sorted(os.listdir(mount))
        except OSError:
            continue
        for storage in storages:
            for name in PHONE_DIRS:
                path = os.path.join(mount, storage, name)
                if os.path.isdir(path):
                    found.append((device_name(os.path.basename(mount)), path))
    return found


def device_name(mount_name):
    """A phone's name from its gvfs mount's (mtp:host=VENDOR_MODEL_SERIAL): its model, e.g. 'Pixel 8'
    (with its vendor, if the model is no name of its own: 'SAMSUNG Android')"""
    words = mount_name[len(MTP_PREFIX):].split('_') if mount_name.startswith(MTP_PREFIX) else [mount_name]
    if len(words) > 1 and _is_serial(words[-1]):
        words = words[:-1]
    if len(words) > 2:
        words = words[1:]
    return ' '.join(words).strip() or mount_name


def _is_serial(word):
    return len(word) >= 6 and word.isalnum() and any(char.isdigit() for char in word)


def describe(source):
    """{'device': the phone's name (or None, for a local dir), 'inner': the path in it (in its storage:
    'DCIM'; a local dir's whole path), 'full': source}"""
    parts = source.split(os.sep)
    mount = next((index for index, part in enumerate(parts) if part.startswith(MTP_PREFIX)), None)
    if mount is None or not source.startswith(GVFS_DIR):
        return {'device': None, 'inner': source, 'full': source}
    inner = parts[mount + 2:] or parts[mount + 1:]
    return {'device': device_name(parts[mount]), 'inner': '/'.join(inner), 'full': source}


def media_files(source, is_stopped=lambda: False):
    """{relpath: (size, mtime)} of the media files under source (images, audio, video), but in
    SKIPPED_DIRS and hidden ones. Raises OSError if source can't be read at all."""
    os.listdir(source)
    found = {}
    for dirpath, dirnames, filenames in os.walk(source):
        if is_stopped():
            break
        dirnames[:] = sorted(name for name in dirnames if name not in SKIPPED_DIRS and not name.startswith('.'))
        for name in sorted(filenames):
            if not media.is_media(name) or name.startswith('.'):
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            found[os.path.relpath(path, source)] = (stat.st_size, int(stat.st_mtime))
    return found
