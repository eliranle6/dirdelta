"""The cache of Google Drive's file list (FILE_LIST_CACHE): one JSON line per file or folder, with
its id, name, parents and mimeType, as the Drive API lists them, after a line with My Drive's root
folder's id (clouddirtreefactory writes it). entries() reads it into the paths of what's under a
folder."""
import collections
import json
import os
import posixpath

FILE_LIST_CACHE = os.path.expanduser('~/.cache/dirman/files.txt')

FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'
# Google's own types (Docs, Sheets, Slides, shortcuts, ...): not files on disk, so never synced
GOOGLE_APPS_MIME_PREFIX = 'application/vnd.google-apps.'
# The key of the cache's line with My Drive's root folder's id
ROOT_ID_KEY = 'myDriveRootId'

# How many of the names to fix an error lists
MAX_PROBLEMS_SHOWN = 20

class DriveCacheError(Exception):
    """The cache can't be read into a tree; the message says why, and what to do"""


def entries(inner_rootpath):
    """Yield (relpath, cloud_id, is_dir) for each file and folder under inner_rootpath (a path in the
    cloud, like /eliran), each folder before what's in it. relpath is relative to inner_rootpath; two
    entries can have the same one, since Drive allows same-named files. Raises DriveCacheError if
    there's no such folder, or if names under it can't be paths: same-named folders (or a folder and
    a file) in one folder, or a '/' in a name."""
    id_child_map, id_md_map, root_cloud_id = _parsefile(FILE_LIST_CACHE)
    inner_rootpath = '/' + '/'.join(component for component in inner_rootpath.split('/') if component)
    found = False
    problems = []
    dfs_stack = [(root_cloud_id, '/')]

    while dfs_stack:
        folder_cloud_id, folder_path = dfs_stack.pop()
        children = [id_md_map[child_id] for child_id in id_child_map.get(folder_cloud_id, [])]

        if _is_at_or_under(folder_path, inner_rootpath):
            found = found or folder_path == inner_rootpath
            problems += _name_problems(folder_path, children)
            for md in children:
                path = posixpath.join(folder_path, md['name'])
                is_dir = md['mimeType'] == FOLDER_MIME_TYPE
                yield (posixpath.relpath(path, inner_rootpath), md['id'], is_dir)
                if is_dir:
                    dfs_stack.append((md['id'], path))
        else:
            # A folder on the way to the inner root: go on only into the next one on the way
            on_the_way = [md for md in children
                          if md['mimeType'] == FOLDER_MIME_TYPE and '/' not in md['name']
                          and _is_at_or_under(inner_rootpath, posixpath.join(folder_path, md['name']))]
            if len(on_the_way) > 1:
                problems.append("%d folders named %s" % (len(on_the_way),
                                                        posixpath.join(folder_path, on_the_way[0]['name'])))
            for md in on_the_way:
                dfs_stack.append((md['id'], posixpath.join(folder_path, md['name'])))

    if problems:
        lines = problems[:MAX_PROBLEMS_SHOWN]
        if len(problems) > MAX_PROBLEMS_SHOWN:
            lines.append("(and %d more)" % (len(problems) - MAX_PROBLEMS_SHOWN,))
        raise DriveCacheError(
            "Some names in Google Drive can't be paths. Rename them in Drive, then run dirdelta "
            "again and refresh the cloud files list cache:\n%s" % ('\n'.join("  " + line for line in lines),))
    if not found:
        raise DriveCacheError("Google Drive has no folder %s (as of the cloud files list cache). Check "
                              "the path, or if the folder is new, refresh the cache." % (inner_rootpath,))


def _is_at_or_under(path, folder_path):
    return path == folder_path or path.startswith(folder_path.rstrip('/') + '/')


def _name_problems(folder_path, children):
    """What's wrong with the names of a folder's children, as paths: a '/' in one, or a folder's name
    that another child has too"""
    problems = ["a '/' in the name of %s" % (posixpath.join(folder_path, md['name']),)
                for md in children if '/' in md['name']]
    kinds_by_name = collections.defaultdict(list)
    for md in children:
        kinds_by_name[md['name']].append(md['mimeType'] == FOLDER_MIME_TYPE)
    for name, kinds in kinds_by_name.items():
        if len(kinds) > 1 and any(kinds):
            problems.append("%d folders or files named %s, in one folder (a folder's name must be "
                            "its own)" % (len(kinds), posixpath.join(folder_path, name)))
    return problems


def _parsefile(filename):
    """Read the cache into an id->children map, an id->metadata map and My Drive's root folder's id.
    Google's own types (Docs, shortcuts, ...) are left out, and so is what isn't in My Drive (files
    shared with the user, which have no parents, or whose parent folder the user can't see)."""
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
            elif md['mimeType'] == FOLDER_MIME_TYPE or not md['mimeType'].startswith(GOOGLE_APPS_MIME_PREFIX):
                id_md_map[md['id']] = md
                if md.get('parents'):
                    id_child_map[md['parents'][0]].append(md['id'])

    if root is None:
        root = _guess_root(id_child_map, id_md_map)
    return id_child_map, id_md_map, root


def _guess_root(id_child_map, id_md_map):
    """My Drive's root folder's id, in a cache from before it was written down: the one folder that
    has children but isn't listed itself, if there's just one"""
    unlisted = set(id_child_map).difference(id_md_map)
    if len(unlisted) != 1:
        raise DriveCacheError("Can't tell which folder is My Drive in the cloud files list cache, "
                              "which is from an older dirdelta: run dirdelta again and refresh it.")
    return unlisted.pop()
