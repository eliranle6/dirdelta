"""What a file's metadata (as Drive gives it) says of it"""
import datetime

from dirdelta.drive.drivecache.names import (FOLDER_MIME_TYPE, GOOGLE_APPS_MIME_PREFIX,
                                             GOOGLE_FILE_EXTENSIONS, HASH_FIELDS)
from dirdelta.util import exif


class DriveCacheError(Exception):
    """The cache can't be read into a tree; the message says why, and what to do"""


def is_google_file(md):
    """Whether the file (its metadata) is one of Google's own types (a Google Doc, ...), not a folder"""
    mime_type = md.get('mimeType', '')
    return mime_type != FOLDER_MIME_TYPE and mime_type.startswith(GOOGLE_APPS_MIME_PREFIX)


def hashes(md):
    """{algorithm (a hashlib name): hex} of the hashes of the file's contents that Drive gave (in
    HASH_FIELDS' order: the fastest first); none for a folder or a Google file"""
    return {algorithm: md[field] for algorithm, field in HASH_FIELDS if field in md}


def modified_time(md):
    """When the file whose metadata md is was last modified (Drive's modifiedTime), in seconds since
    the epoch, or None if the cache doesn't have it (lines from before it was asked for)"""
    modified = md.get('modifiedTime')
    if not modified:
        return None
    try:
        # RFC 3339, in UTC, e.g. 2024-07-01T14:03:22.123Z
        return datetime.datetime.strptime(modified.rstrip('Z').split('.')[0], '%Y-%m-%dT%H:%M:%S').replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def rfc3339(timestamp):
    """A time (seconds since the epoch) as Drive's modifiedTime takes it"""
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def date_taken(md):
    """When the photo whose metadata md is was taken, as exif.date_taken() gives it, or None"""
    taken = md.get('imageMediaMetadata', {}).get('time')
    return exif.normalized(taken) if taken else None


def path_name(md):
    """A file's or folder's name in its path: its name, and for a Google file, its extension (see
    GOOGLE_FILE_EXTENSIONS)"""
    if not is_google_file(md):
        return md['name']
    kind = md['mimeType'][len(GOOGLE_APPS_MIME_PREFIX):]
    return md['name'] + GOOGLE_FILE_EXTENSIONS.get(kind, '.g' + kind)
