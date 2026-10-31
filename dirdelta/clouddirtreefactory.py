import os.path

from dirdelta import clouddirtree
from dirdelta import drivecache
from dirdelta import paths
from dirdelta import picker


# The refresh question's options: the first, selected at first, does nothing
OPTION_NOTHING = 'Nothing: go back'
OPTION_REFRESH = 'Refresh %s from Google Drive'
OPTION_NO_REFRESH = 'Not now: go on with the cloud files list cache'


def factory_interactive(rootpath):
    """The cloud tree at rootpath, from the cache, refreshed first (from Drive) if the user wants,
    or if there's no cache yet. None if the user chose nothing (or quit the question)."""
    if not os.path.exists(drivecache.FILE_LIST_CACHE):
        clouddirtree.refresh_cache(paths.path_in_cloud(rootpath))
    else:
        answer = _ask_whether_to_refresh(rootpath)
        if answer not in (OPTION_REFRESH % (rootpath,), OPTION_NO_REFRESH):
            return None
        if answer == OPTION_REFRESH % (rootpath,):
            clouddirtree.refresh_cache(paths.path_in_cloud(rootpath))
    return clouddirtree.factory(rootpath)


def _ask_whether_to_refresh(rootpath):
    """The user's answer (one of the options), or None if they quit"""
    # Nothing first (selected at first), then going on without refreshing
    options = [OPTION_NOTHING, OPTION_NO_REFRESH, OPTION_REFRESH % (rootpath,)]
    header = ''
    stale = [path for path in drivecache.stale_paths()
             if _overlap(path, paths.path_in_cloud(rootpath))]
    if stale:
        header = ("The cloud files list cache may be out of date in %s: dirdelta was cut off while "
                  "changing it in Google Drive.\nRefresh it to see those changes." %
                  (', '.join(paths.join_cloud(path) for path in stale),))
    return picker.pick_option(options, header=header, title="Google Drive's file list")


def _overlap(path, other):
    """Whether one of the paths (in Drive) is at or under the other"""
    return any(a == b or a.startswith(b.rstrip('/') + '/') for a, b in ((path, other), (other, path)))
