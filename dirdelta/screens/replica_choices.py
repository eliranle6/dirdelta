"""Choosing one replica for a slot: a local dir, a Drive one, or one already known"""
from dirdelta.drive import drivecache
from dirdelta.screens.start_names import CLOUD, CLOUD_ROOT, KNOWN, LOCAL, LOCAL_ROOT
from dirdelta.trees import paths
from dirdelta.trees import replicafactory
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


def known_replicas(replicas):
    """The replicas' paths the user knows, once each: the favorites', the recent pairs', then the
    sorted trees of the recent sorts"""
    found = [path for pair in replicas.favorites + replicas.history for path in pair]
    found += [root for _, root in replicas.sorts]
    return list(dict.fromkeys(found))


def choose_replica(name, known=()):
    """Let the user choose a local dir or a Drive one, or one of known (paths) at once. Returns its
    path, or None if they quit."""
    options = [picker.Option(('known', path), KNOWN + path) for path in known]
    where = picker.pick_option(options + [LOCAL, CLOUD], header='Where is %s?' % (name,),
                               title='Choose %s' % (name,))
    if isinstance(where, tuple):
        return where[1]
    header = 'Choose %s' % (name,)
    key_hints = [('Enter', 'choose the selected dir')]
    if where == LOCAL:
        return picker.pick_under_dir(LOCAL_ROOT, dirs_only=True, lazy=True, header=header, key_hints=key_hints)
    if where == CLOUD:
        try:
            tree = replicafactory.create_dirtree_from_arg(CLOUD_ROOT)
        except drivecache.DriveCacheError as error:
            messages.show("Cannot read Google Drive's file list", str(error).splitlines(),
                          dryrun.label(), 'red')
            return None
        if tree is None:
            return None
        picked = picker.pick_from_tree(tree, header=header, dirs_only=True, key_hints=key_hints)
        # A cloud tree's paths are Drive's (/mein/music), not cloud paths (cloud/mein/music)
        return paths.join_cloud(picked[0].relpath) if picked else None
    return None
