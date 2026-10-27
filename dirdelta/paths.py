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
