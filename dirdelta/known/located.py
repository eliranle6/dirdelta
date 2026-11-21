"""The user's replicas' file's local paths, kept as the replicas' identities (a disk's UUID and the path on it:
replicanames.identity()), so that two disks of one model, mounted at the same mount point, are two replicas (see
mounts/volumes.py): encoded() writes each local path as its identity, decoded() reads each back as where it is now
(on its disk, if it's mounted, else at its placeholder). A file from before, with the paths themselves, is read by
what its 'known' section says each path was (an identity it was seen at), and written as identities next time.
Drive's paths ('cloud/...') are kept as they are."""
from dirdelta.known.mounts import volumes
from dirdelta.trees import paths

IDENTITY_PREFIX = 'uuid:'


def encoded(content):
    """content (the file's JSON, its paths where they are now) with its local paths as identities"""
    from dirdelta.known import replicanames
    where = volumes.mounted()

    def identity(path):
        if not _is_local(path):
            return path
        found = replicanames.label_key(path)
        # (Kept so only if it can be read back: its disk is one mounted now, or it's a placeholder's)
        on_disk = found[len(IDENTITY_PREFIX):].partition(':')[0] if found.startswith(IDENTITY_PREFIX) else None
        return found if on_disk and (on_disk in where or volumes.of_placeholder(path)) else path
    return _mapped(content, identity)


def decoded(content):
    """content (the file's JSON) with its identities as paths where they are now (and a path of a file from before as
    the path its identity is at)"""
    where = volumes.mounted()
    seen_at = {}
    for key, info in (content.get('known') or {}).items():
        if isinstance(info, dict) and key.startswith(IDENTITY_PREFIX):
            for path in info.get('paths') or []:
                # (A path two disks were seen at tells neither)
                seen_at[path] = key if path not in seen_at else None

    def path(value):
        if not isinstance(value, str):
            return value
        if value.startswith(IDENTITY_PREFIX):
            return volumes.located(value, where) or value
        if _is_local(value) and seen_at.get(value):
            return volumes.located(seen_at[value], where)
        return value
    return _mapped(content, path)


def _is_local(path):
    return isinstance(path, str) and path.startswith('/') and not paths.is_cloud_path(path)


def _mapped(content, path):
    """content with path() of each path it has (the pairs', the replicas' and inboxes' lists, the main one, the
    compared pairs', the sorted trees' keys and their followers); the rest as it is"""
    content = dict(content)
    for key in ('favorites', 'history', 'sorts', 'pairs'):
        if isinstance(content.get(key), list):
            content[key] = [[path(one) for one in pair] if isinstance(pair, list) else pair for pair in content[key]]
    for key in ('replicas', 'inboxes'):
        if isinstance(content.get(key), list):
            content[key] = [path(one) for one in content[key]]
    if content.get('main'):
        content['main'] = path(content['main'])
    if isinstance(content.get('compared'), list):
        content['compared'] = [dict(item, pair=[path(one) for one in item['pair']])
                               if isinstance(item, dict) and isinstance(item.get('pair'), list) else item
                               for item in content['compared']]
    if isinstance(content.get('recent_dirs'), dict):
        content['recent_dirs'] = {path(root): dirs for root, dirs in content['recent_dirs'].items()}
    if isinstance(content.get('followers'), dict):
        content['followers'] = {path(root): [path(one) for one in found] if isinstance(found, list) else found
                                for root, found in content['followers'].items()}
    return content
