"""Where an import's files come from: the phones plugged in (phones(): Android's MTP, mounted by GNOME's
gvfs under GVFS_DIR), or any local dir; and a source's media files (media_files()), wherever they are in
it, since phones keep them differently (DCIM/Camera, Pictures/, WhatsApp's dirs...)"""
import glob
import os

from dirdelta.util import media

GVFS_DIR = '/run/user/%d/gvfs' % (os.getuid(),)
# Dirs not looked in: apps' own data, thumbnails, and the trash
SKIPPED_DIRS = {'.thumbnails', '.trashed', '.Trash', 'Android', '.cache', 'cache', 'LOST.DIR'}


def phones():
    """[(name, path)] of the storages of the phones mounted now (e.g. ('Pixel 7: Internal shared storage',
    '/run/user/1000/gvfs/mtp:host=Google_Pixel_7_.../Internal shared storage'))"""
    found = []
    for mount in sorted(glob.glob(os.path.join(GVFS_DIR, 'mtp:host=*'))):
        device = os.path.basename(mount)[len('mtp:host='):].replace('_', ' ').strip()
        try:
            storages = sorted(os.listdir(mount))
        except OSError:
            continue
        for storage in storages:
            path = os.path.join(mount, storage)
            if os.path.isdir(path):
                found.append(('%s: %s' % (device, storage), path))
    return found


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
