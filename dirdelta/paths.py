"""Replica paths, as given on the command line: a cloud (Google Drive) one starts with the component
'cloud' (e.g. cloud/mein/music), a local one is any other."""


def components(path):
    """path's components, without empty ones (so '/cloud//mein/' is ['cloud', 'mein'])"""
    return [component for component in path.split('/') if component]


def is_cloud_path(path):
    return components(path)[:1] == ['cloud']


def path_in_cloud(path):
    """A cloud path's path in the cloud (cloud/mein/music is /mein/music)"""
    return '/' + '/'.join(components(path)[1:])


def join_cloud(relpath):
    """The cloud path of relpath, a path relative to Drive's top (e.g. mein/music, or '' for the
    top itself)"""
    return '/'.join(['cloud'] + components(relpath))


def short_names(replica_paths):
    """{path: a short name for it on the screens} of replica_paths: a cloud path as it is, a local
    one by the fewest of its last components that tell it from the others (its dir's name, unless
    another has the same, e.g. two replicas named eliran: 'win/eliran' and 'usb/eliran')"""
    local = [path for path in dict.fromkeys(replica_paths) if not is_cloud_path(path)]
    names = {path: path for path in replica_paths if is_cloud_path(path)}
    for path in local:
        parts = components(path)
        others = [components(other) for other in local if other != path]
        count = 1
        while count < len(parts) and any(other[-count:] == parts[-count:] for other in others):
            count += 1
        names[path] = '/'.join(parts[-count:]) or '/'
    return names
