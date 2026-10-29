import os.path

from dirdelta import clouddirtree
from dirdelta import drivecache
from dirdelta import paths
from dirdelta import picker


def factory_interactive(rootpath):
    # Make sure the cache has the cloud path, as Drive has it now if the user wants
    if not os.path.exists(drivecache.FILE_LIST_CACHE) or _does_user_want_to_refresh_cache(rootpath):
        clouddirtree.refresh_cache(paths.path_in_cloud(rootpath))
    return clouddirtree.factory(rootpath)


def _does_user_want_to_refresh_cache(rootpath):
    OPTION_REFRESH = 'Refresh %s from Google Drive' % (rootpath,)
    OPTION_NO_REFRESH = 'Continue with the cloud files list cache'
    options = [OPTION_REFRESH, OPTION_NO_REFRESH]
    header = ''
    stale = [path for path in drivecache.stale_paths()
             if _overlap(path, paths.path_in_cloud(rootpath))]
    if stale:
        header = ("The cloud files list cache may be out of date in %s: dirdelta was cut off while "
                  "changing it in Google Drive.\nRefresh it to see those changes." %
                  (', '.join(paths.join_cloud(path) for path in stale),))
    return picker.pick_option(options, header=header) == OPTION_REFRESH


def _overlap(path, other):
    """Whether one of the paths (in Drive) is at or under the other"""
    return any(a == b or a.startswith(b.rstrip('/') + '/') for a, b in ((path, other), (other, path)))
