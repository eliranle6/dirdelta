"""Adding a pair of replicas from the web version (routes()): its folders browsed (this computer's, or
Google Drive's, as the Drive cache has them), then the pair kept as a favorite of the user's, so it's on
Home, Replicas and Sync, synced when they choose (at once, or later)"""
import os

from dirdelta.drive import drivecache
from dirdelta.drive.drivecache import reading as drivecache_reading
from dirdelta.drive.drivecache.metadata import path_name
from dirdelta.drive.drivecache.names import FOLDER_MIME_TYPE
from dirdelta.known import replicas
from dirdelta.trees import paths
from dirdelta.web import naming


def shortcuts():
    """[{'path', 'name'}]: where to start browsing on this computer: home, the mounted disks"""
    found = [os.path.expanduser('~')]
    for top in ('/mnt', '/media', os.path.join('/media', os.path.basename(os.path.expanduser('~')))):
        try:
            found += sorted(entry.path for entry in os.scandir(top) if entry.is_dir() and os.path.ismount(entry.path))
        except OSError:
            pass
    return [{'path': path, 'name': path} for path in dict.fromkeys(found)]


def local_dirs(path):
    """The names of the dirs in a local dir (not hidden ones), sorted"""
    with os.scandir(path) as listing:
        return sorted((entry.name for entry in listing if not entry.name.startswith('.') and entry.is_dir()), key=str.lower)


def drive_dirs(path):
    """The names of the folders in a Drive folder (path: 'cloud' or 'cloud/...'), as the cache has them"""
    id_child_map, id_md_map, folder_id = drivecache_reading.parsefile()
    for name in paths.components(path)[1:]:
        found = [child for child in id_child_map.get(folder_id, [])
                 if id_md_map[child].get('mimeType') == FOLDER_MIME_TYPE and path_name(id_md_map[child]) == name]
        if not found:
            raise FileNotFoundError("Google Drive has no folder %s (as the cache has it)" % (path,))
        folder_id = found[0]
    return sorted((path_name(id_md_map[child]) for child in id_child_map.get(folder_id, [])
                   if id_md_map[child].get('mimeType') == FOLDER_MIME_TYPE and '/' not in id_md_map[child]['name']),
                  key=str.lower)


def browse(path):
    """{'path', 'parent', 'dirs', 'name', 'known'}: the folder at path (local, or 'cloud...'), or {'error'}"""
    is_drive = paths.is_cloud_path(path)
    path = paths.normalized(path) if is_drive else os.path.abspath(path)
    try:
        dirs = drive_dirs(path) if is_drive else local_dirs(path)
    except (OSError, drivecache.DriveCacheError) as error:
        return {'error': str(error), 'path': path}
    parent = None
    if is_drive and path != 'cloud':
        parent = path.rsplit('/', 1)[0]
    elif not is_drive and path != '/':
        parent = os.path.dirname(path)
    known = {replica for pair in _pairs() for replica in pair}
    return {'path': path, 'parent': parent, 'dirs': dirs, 'name': naming.name(path) if path not in ('/', 'cloud') else path,
            'known': path in known}


def _pairs():
    known_replicas = replicas.load()
    return known_replicas.favorites + known_replicas.history + known_replicas.sorts


def problem(path_a, path_b):
    """Why path_a and path_b can't be a pair, or None"""
    for path in (path_a, path_b):
        if not path or path in ('/', 'cloud'):
            return "Choose a folder for each replica (not all of this computer or all of Drive)."
        if not paths.is_cloud_path(path) and not os.path.isdir(path):
            return "%s isn't a folder on this computer." % (path,)
    if paths.is_at_or_under(path_a, path_b) or paths.is_at_or_under(path_b, path_a):
        return "One is inside the other: a replica pair is two separate copies."
    return None


def routes():
    def browse_route(query, body):
        if query.get('path'):
            return browse(query['path'])
        return {'shortcuts': shortcuts()}

    def add(query, body):
        path_a, path_b = (body.get(name) or '' for name in ('a', 'b'))
        path_a, path_b = (paths.normalized(path) if path else '' for path in (path_a, path_b))
        why = problem(path_a, path_b)
        if why:
            return {'ok': False, 'error': why}
        known_replicas = replicas.load()
        if not known_replicas.is_favorite(path_a, path_b):
            known_replicas.toggle_favorite(path_a, path_b)
            replicas.save(known_replicas)
        return {'ok': True, 'a': path_a, 'b': path_b}

    return {('GET', '/api/browse'): browse_route, ('POST', '/api/pairs/add'): add}
