"""Reading the cache into the paths of what's under a folder"""
import collections
import json
import os
import posixpath

from dirdelta.drive.drivecache import database
from dirdelta.drive.drivecache import names
from dirdelta.drive.drivecache.database import database_path, generations, opened, root_of, exists
from dirdelta.drive.drivecache.metadata import (DriveCacheError, date_taken, hashes, is_google_file,
                                                modified_time, path_name)
from dirdelta.drive.drivecache.names import FOLDER_MIME_TYPE, MAX_PROBLEMS_SHOWN
from dirdelta.trees import paths
from dirdelta.util import text


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
    id_child_map, id_md_map, root_cloud_id = parsefile()
    inner_rootpath = '/' + '/'.join(component for component in inner_rootpath.split('/') if component)
    found = False
    problems = []
    dfs_stack = [(root_cloud_id, '/')]

    while dfs_stack:
        folder_cloud_id, folder_path = dfs_stack.pop()
        children = [id_md_map[child_id] for child_id in id_child_map.get(folder_cloud_id, [])]

        if is_at_or_under(folder_path, inner_rootpath):
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
                          and is_at_or_under(inner_rootpath, posixpath.join(folder_path, md['name']))]
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
is_at_or_under = paths.is_at_or_under


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
    """My Drive's root folder's id, as the cache has it, or None if it doesn't (or there's none)"""
    if not exists():
        return None
    try:
        with opened(is_writing=False) as db:
            return root_of(db)
    except (OSError, DriveCacheError):
        return None


# The last parse of the cache, by its database's path: (what changes when it does, what parsefile()
# gave)
_parsed = {}


def parsefile():
    """Read the cache into an id->children map, an id->metadata map and My Drive's root folder's id.
    What isn't in My Drive is left out (files shared with the user, which have no parents, or whose
    parent folder the user can't see). Read again only once it changed: what's given is shared, not to
    be changed. Raises FileNotFoundError if there's no cache."""
    if not exists():
        raise FileNotFoundError("There's no cloud files list cache")
    # Its old file imported first: that changes it
    if os.path.exists(names.LINES_FILE):
        with opened():
            pass
    with opened(is_writing=False) as db:
        path = database_path()
        # data_version: what another process changed
        stamp = (generations[path], database.kept_connection[2], db.execute('PRAGMA data_version').fetchone()[0])
        if path in _parsed and _parsed[path][0] == stamp:
            return _parsed[path][1]
        parsed = _parse(db)
    _parsed[path] = (stamp, parsed)
    return parsed


def _parse(db):
    id_child_map = collections.defaultdict(list)
    id_md_map = {}
    for cloud_id, parent, md in db.execute('SELECT id, parent, md FROM files ORDER BY rowid'):
        id_md_map[cloud_id] = json.loads(md)
        if parent is not None:
            id_child_map[parent].append(cloud_id)
    root = root_of(db)
    if root is None:
        raise DriveCacheError("The cloud files list cache doesn't say which folder is My Drive: run "
                              "dirdelta again and refresh it.")
    return id_child_map, id_md_map, root
