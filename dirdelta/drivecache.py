"""The cache of Google Drive's file list (FILE_LIST_CACHE): one JSON line per file or folder, with
its id, name, parents and mimeType, as the Drive API lists them, after a line with My Drive's root
folder's id (clouddirtreefactory writes it). entries() reads it into the paths of what's under a
folder.

What dirdelta changes in Drive is added to it as it goes (add(), trash()), so it stays up to date:
a line per file or folder made, and a line with the id of each file moved to the trash. What's under
a folder is replaced with what Drive lists there now (replace_under()) when it's refreshed."""
import collections
import contextlib
import datetime
import json
import os
import posixpath
import threading
import time

from dirdelta import exif
from dirdelta import paths
from dirdelta import text

FILE_LIST_CACHE = os.path.expanduser('~/.cache/dirman/files.txt')

FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'
# Google's own types (Docs, Sheets, Slides, shortcuts, ...): not files, so they can't be downloaded
# (only exported to another format), but they're in Drive's folders, so they're in the tree
GOOGLE_APPS_MIME_PREFIX = 'application/vnd.google-apps.'
# What's added to a Google file's name in its path, so it's told from a file, as Google Drive for
# desktop names them on disk (a Google Sheet "Budget" is Budget.gsheet), by its mimeType's last part.
# Others get ".g" and that part.
GOOGLE_FILE_EXTENSIONS = {
    'document': '.gdoc',
    'spreadsheet': '.gsheet',
    'presentation': '.gslides',
    'drawing': '.gdraw',
    'form': '.gform',
    'shortcut': '.glink',
}
# The key of the cache's line with My Drive's root folder's id
ROOT_ID_KEY = 'myDriveRootId'
# The key of a line with the id of a file that dirdelta moved to the trash since the scan
TRASHED_ID_KEY = 'trashedId'
# The fields of a file or folder that the cache has, for the Drive API
FILE_FIELDS = ('id, name, parents, kind, size, mimeType, modifiedTime, sha1Checksum, sha256Checksum, '
               'imageMediaMetadata(time)')
# The hashes of a file's contents that Drive gives, by their hashlib names: the fastest to work out
# first (SHA-1 is about twice as fast as SHA-256), for comparing with a local file
HASH_FIELDS = (('sha1', 'sha1Checksum'), ('sha256', 'sha256Checksum'))

# How many of the names to fix an error lists
MAX_PROBLEMS_SHOWN = 20

def _stale_marker_path():
    # Next to the cache (wherever it is, e.g. in tests)
    return FILE_LIST_CACHE + '.stale'


def mark_stale(folder_path):
    """Note that dirdelta is changing what's under folder_path (a path in Drive, like /eliran) in
    Drive, so the cache may not have it, until unmark_stale() (once the changes are in the cache) or
    a refresh of it. Returns whether it wasn't marked already."""
    if folder_path in stale_paths():
        return False
    with open(_stale_marker_path(), 'a') as marker:
        marker.write(folder_path + '\n')
    return True


class _Changing(object):
    """What changing() gives: settled says the cache has what was done, even if a Ctrl-C comes"""
    def __init__(self):
        self.settled = False


@contextlib.contextmanager
def changing(folder_path):
    """Around a change dirdelta makes under folder_path in Drive (and adds to the cache): it's marked
    stale (mark_stale()) while it's made, and unmarked after (unless it was marked before): when it
    ends, or fails with an exception (e.g. an HttpError: Drive changed nothing), but not when it's
    cut off by Ctrl-C (Drive may or may not have the change), unless what it gives (a _Changing) was
    made settled first (e.g. the uploads under way were waited for)"""
    is_newly_stale = mark_stale(folder_path)
    changes = _Changing()
    try:
        yield changes
    except KeyboardInterrupt:
        if is_newly_stale and changes.settled:
            unmark_stale(folder_path)
        raise
    except BaseException:
        if is_newly_stale:
            unmark_stale(folder_path)
        raise
    if is_newly_stale:
        unmark_stale(folder_path)


def unmark_stale(folder_path):
    """Undo mark_stale(folder_path)"""
    _keep_stale_paths(lambda path: path != folder_path)


def mark_fresh(folder_path='/'):
    """Note that what's under folder_path (default: all of My Drive) was just read from Drive, so
    the cache has it as it is"""
    _keep_stale_paths(lambda path: not _is_at_or_under(path, folder_path))


def stale_paths():
    """The folders (paths in Drive) the cache may be out of date in: what's under them was being
    changed by dirdelta when it was cut off"""
    if not os.path.exists(_stale_marker_path()):
        return []
    with open(_stale_marker_path()) as marker:
        return marker.read().splitlines()


def _keep_stale_paths(keep):
    paths = [path for path in stale_paths() if keep(path)]
    if paths:
        with open(_stale_marker_path(), 'w') as marker:
            marker.write(''.join(path + '\n' for path in dict.fromkeys(paths)))
    elif os.path.exists(_stale_marker_path()):
        os.remove(_stale_marker_path())


def _times_path():
    # Next to the cache (wherever it is, e.g. in tests)
    return FILE_LIST_CACHE + '.times'


def _times():
    """What's kept of when the cache's folders were updated: {'updated': {folder path: when (seconds
    since the epoch) the cache's list of what's under it was last made as Drive has it (read, or
    changed by dirdelta)}, 'uploaded': {folder path: {'modified': the modifiedTime of the copy of
    it last uploaded to Drive, or used from there (see drivemeta.py), 'as_of': the cache's updated()
    of it then}}}"""
    try:
        with open(_times_path()) as times_file:
            times = json.load(times_file)
        if isinstance(times, dict):
            return {'updated': dict(times.get('updated') or {}), 'uploaded': dict(times.get('uploaded') or {}),
                    'user': times.get('user')}
    except (OSError, ValueError):
        pass
    return {'updated': {}, 'uploaded': {}, 'user': None}


def _save_times(times):
    tmp_path = _times_path() + '.tmp'
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, 'w') as times_file:
        json.dump(times, times_file, indent=1)
    os.replace(tmp_path, _times_path())


def note_user(name):
    """Note the Drive account's user name, to say it on the screens"""
    times = _times()
    times['user'] = name
    _save_times(times)


def user():
    """The Drive account's user name, if it's known"""
    return _times()['user']


def note_updated(folder_path, when=None):
    """Note that the cache has what's under folder_path (a path in Drive) as Drive had it at when
    (seconds since the epoch; default: now): read anew, or changed by dirdelta"""
    times = _times()
    times['updated'][_clean(folder_path)] = time.time() if when is None else when
    _save_times(times)


def updated(folder_path):
    """When the cache's list of folder_path was last updated (see note_updated()), by the latest of
    its own, a folder's above it (read with it) or under it (a change in it): seconds since the
    epoch, or None if it's not known"""
    folder_path = _clean(folder_path)
    found = [when for path, when in _times()['updated'].items()
             if _is_at_or_under(path, folder_path) or _is_at_or_under(folder_path, path)]
    return max(found) if found else None


def note_uploaded(folder_path, modified, as_of):
    """Note that the copy of folder_path's list in Drive (see drivemeta.py) has Drive's modifiedTime
    modified, the one this cache made (or used), when the cache's list was updated as of as_of (see
    updated())"""
    times = _times()
    times['uploaded'][_clean(folder_path)] = {'modified': modified, 'as_of': as_of}
    _save_times(times)


def uploaded(folder_path):
    """What note_uploaded() noted of folder_path: {'modified': ..., 'as_of': ...}, or None"""
    found = _times()['uploaded'].get(_clean(folder_path))
    return found if isinstance(found, dict) else None


def _clean(folder_path):
    return '/' + '/'.join(paths.components(folder_path))


def under(folder_id, left_out=()):
    """The metadata of what the cache has under the folder with folder_id (the files and folders in
    it, and in those, ...), each folder before what's in it, without what's under the folders whose
    ids are in left_out (nor them)"""
    id_child_map, id_md_map, _ = _parsefile(FILE_LIST_CACHE)
    found = []
    stack = [folder_id]
    while stack:
        for child_id in id_child_map.get(stack.pop(), []):
            if child_id in left_out:
                continue
            found.append(id_md_map[child_id])
            stack.append(child_id)
    return found


def add(md):
    """Add a file or folder that was made in Drive (its metadata, as the Drive API gives it)"""
    _append(md)


def trash(cloud_id):
    """Note that the file or folder with the id was moved to the trash"""
    _append({TRASHED_ID_KEY: cloud_id})


def replace_under(folder_id, items, my_drive_id):
    """Replace what the cache has under the folder with folder_id (the files and folders in it, and
    in those, ...) with items (their metadata, as the Drive API lists them, FILE_FIELDS), e.g. what
    Drive lists under it now. The folder's own line stays. With no cache, make one, with My Drive's
    root folder's id (my_drive_id) and items. Rewrites the whole cache, into a temporary file first,
    which then takes its place, so it's never left half written (nor made half written)."""
    tmp_path = FILE_LIST_CACHE + '.tmp'
    # (Without the root's line, it can't be read: what's listed now is all it has)
    if root_id() is None:
        os.makedirs(os.path.dirname(FILE_LIST_CACHE), exist_ok=True)
        with open(tmp_path, 'w') as new:
            new.write(json.dumps({ROOT_ID_KEY: my_drive_id}) + '\n')
            for md in items:
                new.write(json.dumps(md) + '\n')
        os.replace(tmp_path, FILE_LIST_CACHE)
        return
    id_child_map, _, _ = _parsefile(FILE_LIST_CACHE)
    under = set()
    stack = [folder_id]
    while stack:
        for child_id in id_child_map.get(stack.pop(), []):
            under.add(child_id)
            stack.append(child_id)
    with open(FILE_LIST_CACHE) as old, open(tmp_path, 'w') as new:
        for line in old:
            # A trashed line stays: what's under the folder now comes after it, so it's in
            if line.startswith('{') and json.loads(line).get('id') in under:
                continue
            new.write(line)
        for md in items:
            new.write(json.dumps(md) + '\n')
    os.replace(tmp_path, FILE_LIST_CACHE)


def _append(line):
    with open(FILE_LIST_CACHE, 'a') as f:
        f.write(json.dumps(line) + '\n')


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


# What entries() yields: size is a file's size in bytes, or None for a folder or a Google file (which
# Drive gives none), date_taken a photo's (as exif.date_taken() gives it), if Drive knows it (and
# the cache has it: lines from before it was asked for don't), and hashes its contents' hashes
# (see hashes()), and modified when it was last modified (see modified_time())
Entry = collections.namedtuple('Entry', ['relpath', 'cloud_id', 'is_dir', 'is_google_file', 'size',
                                         'date_taken', 'hashes', 'modified'])


def entries(inner_rootpath):
    """Yield an Entry (relpath, cloud_id, is_dir, is_google_file, size, date_taken, hashes, modified)
    for inner_rootpath (a path in the cloud,
    like /eliran), whose relpath is '', and each file and folder under it, each folder before what's
    in it. relpath is relative to inner_rootpath, and ends with a Google file's extension (see
    path_name()); two entries can have the same one, since Drive allows same-named files. Raises
    DriveCacheError if there's no such folder, or if names under it can't be paths: same-named
    folders (or a folder and a file) in one folder, or a '/' in a name."""
    id_child_map, id_md_map, root_cloud_id = _parsefile(FILE_LIST_CACHE)
    inner_rootpath = '/' + '/'.join(component for component in inner_rootpath.split('/') if component)
    found = False
    problems = []
    dfs_stack = [(root_cloud_id, '/')]

    while dfs_stack:
        folder_cloud_id, folder_path = dfs_stack.pop()
        children = [id_md_map[child_id] for child_id in id_child_map.get(folder_cloud_id, [])]

        if _is_at_or_under(folder_path, inner_rootpath):
            if folder_path == inner_rootpath:
                found = True
                yield Entry('', folder_cloud_id, True, False, None, None, {}, None)
            problems += _name_problems(folder_path, children)
            for md in children:
                path = posixpath.join(folder_path, path_name(md))
                is_dir = md.get('mimeType') == FOLDER_MIME_TYPE
                yield Entry(posixpath.relpath(path, inner_rootpath), md['id'], is_dir, is_google_file(md),
                            int(md['size']) if 'size' in md else None, date_taken(md),
                            hashes(md), modified_time(md))
                if is_dir:
                    dfs_stack.append((md['id'], path))
        else:
            # A folder on the way to the inner root: go on only into the next one on the way
            on_the_way = [md for md in children
                          if md.get('mimeType') == FOLDER_MIME_TYPE and '/' not in md['name']
                          and _is_at_or_under(inner_rootpath, posixpath.join(folder_path, md['name']))]
            if len(on_the_way) > 1:
                problems.append("%d folders named %s" % (len(on_the_way),
                                                        posixpath.join(folder_path, on_the_way[0]['name'])))
            for md in on_the_way:
                dfs_stack.append((md['id'], posixpath.join(folder_path, md['name'])))

    if problems:
        lines = text.listed(problems, MAX_PROBLEMS_SHOWN, indent='')
        raise DriveCacheError(
            "Some names in Google Drive can't be paths. Rename them in Drive, then run dirdelta "
            "again and refresh the cloud files list cache:\n%s" % ('\n'.join("  " + line for line in lines),))
    if not found:
        raise DriveCacheError("Google Drive has no folder %s (as of the cloud files list cache). Check "
                              "the path, or if the folder is new, refresh the cache." % (inner_rootpath,))


def count_under(folder_path):
    """How many files and folders the cache has under folder_path (a path in Drive), or None if it
    can't say (there's no cache, or no such folder in it)"""
    try:
        return sum(1 for _ in entries(folder_path)) - 1
    except (OSError, DriveCacheError):
        return None


# One answer for all (see paths.is_at_or_under()): the root has all
_is_at_or_under = paths.is_at_or_under


def _name_problems(folder_path, children):
    """What's wrong with the names of a folder's children, as paths: a '/' in one, or a folder's name
    that another child has too"""
    problems = ["a '/' in the name of %s" % (posixpath.join(folder_path, md['name']),)
                for md in children if '/' in md['name']]
    kinds_by_name = collections.defaultdict(list)
    for md in children:
        kinds_by_name[path_name(md)].append(md.get('mimeType') == FOLDER_MIME_TYPE)
    for name, kinds in kinds_by_name.items():
        if len(kinds) > 1 and any(kinds):
            problems.append("%d folders or files named %s, in one folder (a folder's name must be "
                            "its own)" % (len(kinds), posixpath.join(folder_path, name)))
    return problems


def root_id():
    """My Drive's root folder's id, as the cache has it (its first lines), or None if it doesn't"""
    try:
        with open(FILE_LIST_CACHE) as f:
            for line in f:
                if line.startswith('{'):
                    md = json.loads(line)
                    if ROOT_ID_KEY in md:
                        return md[ROOT_ID_KEY]
                    return None
    except (OSError, ValueError):
        pass
    return None


# The last parse of each cache file, by its file: (its (inode, size, mtime), what _parsefile() gave)
_parsed = {}
_parsed_lock = threading.Lock()


def _parsefile(filename):
    """Read the cache into an id->children map, an id->metadata map and My Drive's root folder's id.
    What isn't in My Drive is left out (files shared with the user, which have no parents, or whose
    parent folder the user can't see). Parsed again only once the file changed (by its inode, size
    and modification time): what's given is shared, not to be changed."""
    stat = os.stat(filename)
    stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    with _parsed_lock:
        if filename in _parsed and _parsed[filename][0] == stamp:
            return _parsed[filename][1]
        parsed = _parse(filename)
        _parsed[filename] = (stamp, parsed)
        return parsed


def _parse(filename):
    id_child_map = collections.defaultdict(list)
    id_md_map = {}
    root = None

    with open(filename) as f:
        for line in f:
            # Skip non-dict lines
            if not line.startswith('{'):
                continue
            md = json.loads(line)
            if ROOT_ID_KEY in md:
                root = md[ROOT_ID_KEY]
            elif TRASHED_ID_KEY in md:
                id_md_map.pop(md[TRASHED_ID_KEY], None)
            else:
                id_md_map[md['id']] = md
    # Once all are read, since a line may trash what an earlier one listed
    for cloud_id, md in id_md_map.items():
        if md.get('parents'):
            id_child_map[md['parents'][0]].append(cloud_id)

    if root is None:
        raise DriveCacheError("The cloud files list cache doesn't say which folder is My Drive: run "
                              "dirdelta again and refresh it.")
    return id_child_map, id_md_map, root
