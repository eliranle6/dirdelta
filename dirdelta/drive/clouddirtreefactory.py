import time

from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from dirdelta.trees import paths
from dirdelta.ui import picker


# The refresh question's options: the first, selected at first, does nothing
OPTION_NOTHING = 'Nothing: go back'
OPTION_REFRESH = 'Refresh now'
OPTION_NO_REFRESH = 'Not now'


def factory_interactive(rootpath):
    """The cloud tree at rootpath, from the cache, refreshed first (from Drive) if the user wants,
    or if there's no cache yet. None if the user chose nothing (or quit the question)."""
    if not drivecache.exists():
        clouddirtree.refresh_cache(paths.path_in_cloud(rootpath))
    else:
        answer = _ask_whether_to_refresh(rootpath)
        if answer not in (OPTION_REFRESH, OPTION_NO_REFRESH):
            return None
        if answer == OPTION_REFRESH:
            clouddirtree.refresh_cache(paths.path_in_cloud(rootpath))
    return clouddirtree.factory(rootpath)


def _ask_whether_to_refresh(rootpath):
    """The user's answer (one of the options), or None if they quit"""
    # Nothing first (selected at first), then going on without refreshing
    options = [OPTION_NOTHING, OPTION_NO_REFRESH, OPTION_REFRESH]
    folder = paths.path_in_cloud(rootpath)
    updated = drivecache.updated(folder)
    lines = ["Refresh %s from Google Drive?" % (rootpath,), "",
             ("Its file list is from %s." % (time.strftime('%Y-%m-%d %H:%M', time.localtime(updated)),)
              if updated is not None else "Its file list is from an earlier run.") +
             " Refreshing shows changes made elsewhere, but takes a while."]
    stale = [path for path in drivecache.stale_paths() if _overlap(path, folder)]
    if stale:
        lines.append("It may be out of date in %s: dirdelta was cut off there." %
                     (', '.join(paths.join_cloud(path) for path in stale),))
    return picker.pick_option(options, header='\n'.join(lines), title="Refresh?")


def _overlap(path, other):
    """Whether one of the paths (in Drive) is at or under the other"""
    return paths.is_at_or_under(path, other) or paths.is_at_or_under(other, path)
