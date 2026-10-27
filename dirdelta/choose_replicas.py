"""The menu that chooses what to sync, when dirdelta is run without paths: a replica for each of its
two slots (a local dir under /, or a Drive one), or a favorite or recent pair at once."""
import os

from dirdelta import drivecache
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import utils

NOT_CHOSEN = '<none: press Enter to choose one>'
LOCAL = 'Local disk'
CLOUD = 'Google Drive'
QUIT = 'Quit'

# Where a local replica is browsed from, and a cloud one (all of Drive)
LOCAL_ROOT = '/'
CLOUD_ROOT = 'cloud'


def run(replicas):
    """Let the user choose two replicas, from replicas' (a Replicas) favorites and history or each
    on its own. Returns their paths (a, b), or None if the user quit."""
    chosen = [None, None]
    while True:
        slots = {'Replica %s: %s' % (name, path or NOT_CHOSEN): index
                 for index, (name, path) in enumerate(zip('AB', chosen))}
        pairs = {}
        for prefix, section in (('Favorite', replicas.favorites), ('Recent', replicas.recent())):
            for pair in section:
                pairs['%s: %s' % (prefix, pair_label(*pair))] = pair
        option = picker.pick_option(list(slots) + list(pairs) + [QUIT],
                                    header='Choose the two replicas to sync')
        if option in (None, QUIT):
            return None
        if option in pairs:
            # A favorite or recent pair's local dir may be gone since (a cloud one is checked when
            # the sync reads Drive's file list)
            missing = [path for path in pairs[option]
                       if not paths.is_cloud_path(path) and not os.path.isdir(path)]
            if missing:
                messages.show("No such directory",
                              ["%s is not a directory (anymore?)." % (path,) for path in missing],
                              dryrun.label(), 'red')
                continue
            return pairs[option]
        index = slots[option]
        path = _choose_replica('Replica %s' % ('AB'[index],))
        if path is None:
            continue
        chosen[index] = path
        if None not in chosen:
            if chosen[0] == chosen[1]:
                messages.show("Same replica",
                              ["Both replicas are %s: choose another one." % (path,)], dryrun.label())
                chosen[index] = None
                continue
            return tuple(chosen)


def pair_label(path_a, path_b):
    return '%s <-> %s' % (path_a, path_b)


def _choose_replica(name):
    """Let the user choose a local dir or a Drive one. Returns its path, or None if they quit."""
    where = picker.pick_option([LOCAL, CLOUD], header='Where is %s?' % (name,))
    header = 'Choose %s (Enter picks the selected dir)' % (name,)
    if where == LOCAL:
        return picker.pick_under_dir(LOCAL_ROOT, dirs_only=True, lazy=True, header=header)
    if where == CLOUD:
        try:
            tree = utils.create_dirtree_from_arg(CLOUD_ROOT)
        except drivecache.DriveCacheError as error:
            messages.show("Cannot read Google Drive's file list", str(error).splitlines(),
                          dryrun.label(), 'red')
            return None
        picked = picker.pick_from_tree(tree, header=header, dirs_only=True)
        # A cloud tree's paths are Drive's (/mein/music), not cloud paths (cloud/mein/music)
        return paths.join_cloud(picked[0].relpath) if picked else None
    return None
