"""Where an import's files come from: the phones plugged in (phones(): Android's MTP, mounted by GNOME's
gvfs under GVFS_DIR), a Drive folder (an inbox of the sorts, e.g. one the phone backs up to:
drive_inboxes()), or any local dir; and a source's media files (media_files()), wherever they are in it,
since phones keep them differently (DCIM/Camera, Pictures/, WhatsApp's dirs...)"""
import glob
import os

from dirdelta.drive import drivecache
from dirdelta.known import replicas
from dirdelta.trees import paths
from dirdelta.util import media

GVFS_DIR = '/run/user/%d/gvfs' % (os.getuid(),)
# Dirs not looked in: apps' own data, thumbnails, and the trash
SKIPPED_DIRS = {'.thumbnails', '.trashed', '.Trash', 'Android', '.cache', 'cache', 'LOST.DIR'}


# The dirs of a phone's storage imported from: its camera's (DCIM: photos, videos, screenshots), and WhatsApp's photos
# and videos (where newer Androids keep them, under Android/media, and where older ones did); each a phone's
# storage's import has those of them it has (a phone's source is its storage: phones())
WHATSAPP_MEDIA = ('Android/media/com.whatsapp/WhatsApp/Media', 'WhatsApp/Media')
PHONE_DIRS = ('DCIM',) + tuple('%s/%s' % (media_dir, name) for media_dir in WHATSAPP_MEDIA
                               for name in ('WhatsApp Images', 'WhatsApp Video'))
# In WhatsApp's dirs, what the user sent (Sent/) is imported too: a photo taken with WhatsApp's own camera is only
# there (a photo sent from the gallery is there too, as WhatsApp made it smaller: another file than the gallery's)
SKIPPED_PHONE_SUBDIRS = set()
MTP_PREFIX = 'mtp:host='


def phones():
    """[(name, path)] of the storages of the phones mounted now that have any of PHONE_DIRS, e.g. ('Pixel 8',
    '/run/user/1000/gvfs/mtp:host=Google_Pixel_8_.../Internal shared storage'): each a source, of those dirs' photos"""
    found = []
    for mount in sorted(glob.glob(os.path.join(GVFS_DIR, MTP_PREFIX + '*'))):
        try:
            storages = sorted(os.listdir(mount))
        except OSError:
            continue
        for storage in storages:
            path = os.path.join(mount, storage)
            if phone_dirs(path):
                found.append((device_name(os.path.basename(mount)), path))
    return found


def phone_id(source):
    """The phone a source of it (its storage, or a dir in it) is on, by its USB link's name, which has its serial
    (gvfs's mtp:host=VENDOR_MODEL_SERIAL: 'SAMSUNG_SAMSUNG_Android_RZCY502XMHE'); None if source isn't a phone's"""
    if not source.startswith(GVFS_DIR):
        return None
    for part in source.split(os.sep):
        if part.startswith(MTP_PREFIX):
            return part[len(MTP_PREFIX):]
    return None


def phone_dirs(storage):
    """The ones of PHONE_DIRS the phone's storage (its path) has"""
    return [name for name in PHONE_DIRS if os.path.isdir(os.path.join(storage, name))]


def is_phone_storage(source):
    """Whether source is a phone's storage (phones()'s: its PHONE_DIRS imported), not a dir in it (an import from
    before, of its DCIM alone) nor another dir"""
    parts = source.split(os.sep)
    return (source.startswith(GVFS_DIR) and len(parts) >= 2 and parts[-2].startswith(MTP_PREFIX))


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


def drive_inboxes():
    """[(name, path)] of the Drive folders photos are sorted from: the user's inboxes in Drive"""
    found = [inbox for inbox in replicas.load().inbox_paths() if paths.is_cloud_path(inbox)]
    return [(os.path.basename(path.rstrip('/')), path) for path in found]


# The groups an import's files are shown in, by where they are in the source: (key, title)
CAMERA, WHATSAPP_IMAGES, WHATSAPP_VIDEO, OTHER, ALL = 'camera', 'whatsapp-images', 'whatsapp-video', 'other', 'all'
GROUP_TITLES = {CAMERA: 'Camera (DCIM)', WHATSAPP_IMAGES: 'WhatsApp images', WHATSAPP_VIDEO: 'WhatsApp videos',
                OTHER: 'Other', ALL: 'Files'}


def group_of(source, relpath):
    """The group (a key of GROUP_TITLES) of the file at relpath of source: a phone's by the dir it's in (its camera's,
    WhatsApp's images or videos), any other source's all one"""
    parts = relpath.split('/')
    if is_phone_storage(source):
        if parts[0] == 'DCIM':
            return CAMERA
        if 'WhatsApp Images' in parts:
            return WHATSAPP_IMAGES
        if 'WhatsApp Video' in parts:
            return WHATSAPP_VIDEO
        return OTHER
    # (An import from before of a phone's DCIM alone: its camera's)
    return CAMERA if sources_dcim(source) else ALL


def sources_dcim(source):
    return source.startswith(GVFS_DIR) and os.path.basename(source.rstrip('/')) == 'DCIM'


def describe(source):
    """{'device': the phone's name (or None, for a dir), 'drive': whether it's a Drive folder, 'inner':
    the path in it (in a phone's storage: 'DCIM'; a dir's whole path), 'full': source}"""
    if paths.is_cloud_path(source):
        return {'device': None, 'drive': True, 'inner': source, 'full': source}
    parts = source.split(os.sep)
    mount = next((index for index, part in enumerate(parts) if part.startswith(MTP_PREFIX)), None)
    if mount is None or not source.startswith(GVFS_DIR):
        return {'device': None, 'drive': False, 'inner': source, 'full': source}
    inner = parts[mount + 2:] or parts[mount + 1:]
    found = {'device': device_name(parts[mount]), 'drive': False, 'inner': '/'.join(inner), 'full': source}
    if is_phone_storage(source):
        # (What's imported from it, by name: DCIM, WhatsApp Images, WhatsApp Video; those it has, if it's plugged in)
        there = phone_dirs(source) if os.path.isdir(source) else PHONE_DIRS
        found['folders'] = list(dict.fromkeys(os.path.basename(name) for name in there))
    return found


# What's imported: photos and videos (not audio: a phone's recordings and music aren't sorted here)
PHOTO_EXTENSIONS = frozenset(media.IMAGE_EXTENSIONS + media.VIDEO_EXTENSIONS)


def is_photo(name):
    """Whether the file named name is a photo or a video, by its extension"""
    return media.extension(name) in PHOTO_EXTENSIONS


def drive_media_files(source):
    """{relpath: (size, mtime, sha1)} of the media files under the Drive folder source, as the Drive
    cache has them (Drive's own SHA-1s: nothing to hash). Raises OSError if the cache has no such folder."""
    found = {}
    try:
        for entry in drivecache.entries(paths.path_in_cloud(source)):
            name = os.path.basename(entry.relpath)
            if entry.is_dir or entry.size is None or not is_photo(name) or name.startswith('.'):
                continue
            found[entry.relpath] = (entry.size, int(entry.modified or 0), entry.hashes.get('sha1'))
    except drivecache.DriveCacheError as error:
        raise OSError(str(error))
    return found


def media_files(source, is_stopped=lambda: False):
    """{relpath: (size, mtime)} of the photos and videos under source, but in
    SKIPPED_DIRS and hidden ones; a phone's storage's, in its PHONE_DIRS (and what was sent).
    Raises OSError if source can't be read at all."""
    os.listdir(source)
    if not is_phone_storage(source):
        return _media_under(source, source, SKIPPED_DIRS, is_stopped)
    found = {}
    for name in phone_dirs(source):
        found.update(_media_under(source, os.path.join(source, name), SKIPPED_DIRS | SKIPPED_PHONE_SUBDIRS, is_stopped))
    return found


def _media_under(source, top, skipped, is_stopped):
    """{relpath under source: (size, mtime)} of the photos and videos under top, but in skipped and hidden dirs"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(top):
        if is_stopped():
            break
        dirnames[:] = sorted(name for name in dirnames if name not in skipped and not name.startswith('.'))
        for name in sorted(filenames):
            if not is_photo(name) or name.startswith('.'):
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            found[os.path.relpath(path, source)] = (stat.st_size, int(stat.st_mtime))
    return found
