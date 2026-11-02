"""The menu that chooses what to sync, when dirdelta is run without paths: a replica for each of its
two slots (a local dir under /, or a Drive one), or a favorite or recent pair at once; or an inbox
to sort into a sorted tree (inbox.py), a new one or a recent one. Each kind is a section of its own,
under a heading."""
import collections
import os

from dirdelta import drivecache
from dirdelta import hashes_screen
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicanames
from dirdelta import replicainfo
from dirdelta import syncstate
from dirdelta import replicafactory

NOT_CHOSEN = '<none: press Enter to choose one>'
LOCAL = 'Local disk'
CLOUD = 'Google Drive'
QUIT = 'Quit'
KNOWN_LIST = '  Replicas dashboard: every known replica (last updates, files, hashes)'
SORT = '  New sort: choose an inbox, and the sorted tree its files go to (with Claude\'s help)'
# The menu's sections' headings (shown in grey, and skipped when moving: they can't be picked)
SYNC_SECTION = '\u2500\u2500 Sync two replicas \u2500\u2500'
RECENT_SYNCS_SECTION = '\u2500\u2500 Recent syncs \u2500\u2500'
SORT_SECTION = '\u2500\u2500 Sort an inbox into a sorted tree \u2500\u2500'
RECENT_SORTS_SECTION = '\u2500\u2500 Recent inbox sorts \u2500\u2500'
REPLICAS_SECTION = '\u2500\u2500 Replicas \u2500\u2500'
# What a replica the user knows is offered as, when choosing a sorted tree
KNOWN = 'Known replica: '

# What run() returns for an inbox to sort (rather than a pair to sync)
Sort = collections.namedtuple('Sort', ['inbox', 'root'])

# Where a local replica is browsed from, and a cloud one (all of Drive)
LOCAL_ROOT = '/'
CLOUD_ROOT = 'cloud'


def run(replicas):
    """Let the user choose two replicas, from replicas' (a Replicas) favorites and history or each
    on its own. Returns their paths (a, b); or a Sort, if they chose an inbox to sort (a new one, or
    one of replicas' sorts); or None if the user quit. Whether they can be used now is the caller's
    to check (main: their volumes, then are_there()), back to this menu if not."""
    chosen = [None, None]
    while True:
        slots = [picker.Option(('slot', index), slot_label(name, path)) for index, (name, path) in enumerate(zip('AB', chosen))]
        # How fresh each is, in colors (see styled_pair())
        favorites = [_pair_option(favorite_label(*pair, known=replicas), pair, replicas) for pair in replicas.favorites]
        recent = [_pair_option(recent_label(*pair, known=replicas), pair, replicas) for pair in replicas.recent()]
        sorts = [picker.Option(('sort', Sort(*sort)), sort_label(*sort)) for sort in replicas.sorts]
        sections = [(SYNC_SECTION, slots + favorites), (RECENT_SYNCS_SECTION, recent),
                    (SORT_SECTION, [SORT]), (RECENT_SORTS_SECTION, sorts),
                    (REPLICAS_SECTION, [KNOWN_LIST] if replicas.known else [])]
        # Quit apart from the last section too
        options = picker.grouped([[picker.Skipped(heading)] + section for heading, section in sections if section] + [[QUIT]])
        option = picker.pick_option(options, header='Choose the two replicas to sync, or an inbox to sort',
                                    selected=('slot', 0), help_lines=help_lines())
        if option in (None, QUIT):
            return None
        if option == KNOWN_LIST:
            hashes_screen.dashboard(known=replicas, other_paths=known_paths(replicas))
            continue
        if option == SORT:
            sort = _choose_sort(replicas)
            if sort is not None:
                return sort
            continue
        if option[0] in ('sort', 'pair'):
            return option[1]
        index = option[1]
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


def _pair_option(label, pair, known):
    return picker.Option(('pair', tuple(pair)), label, styled_pair(label, pair[0], pair[1], known))


def _choose_sort(replicas):
    """Let the user choose an inbox and the sorted tree to sort it into: one of the replicas they
    know (replicas', a Replicas), or any dir. Returns a Sort, or None."""
    inbox = _choose_replica('the inbox (the dir of files to sort)')
    if inbox is None:
        return None
    root = _choose_replica('the sorted tree (where its files go)',
                           [path for path in known_replicas(replicas) if path != inbox])
    if root is None:
        return None
    return Sort(inbox, root)


def are_there(replica_paths):
    """Whether the local dirs of what was chosen (a sort's or a pair's replicas), on volumes that are
    mounted by now, are there: they may be gone since (a cloud one is checked when its Drive file
    list is read); if not, it's said why"""
    missing = [path for path in replica_paths if not paths.is_cloud_path(path) and not os.path.isdir(path)]
    if missing:
        messages.show("No such directory", ["%s is not a directory (anymore?)." % (path,) for path in missing],
                      dryrun.label(), 'red')
        return False
    return True


def known_replicas(replicas):
    """The replicas' paths the user knows, once each: the favorites', the recent pairs', then the
    sorted trees of the recent sorts"""
    found = [path for pair in replicas.favorites + replicas.history for path in pair]
    found += [root for _, root in replicas.sorts]
    return list(dict.fromkeys(found))



def slot_label(name, path):
    return '  Replica %s: %s' % (name, path or NOT_CHOSEN)


def favorite_label(path_a, path_b, known=None):
    return '  Favorite: %s' % (pair_label(path_a, path_b, known),)


def recent_label(path_a, path_b, known=None):
    return '  %s' % (pair_label(path_a, path_b, known),)


def sort_label(inbox, root):
    return '  %s -> %s' % (inbox, root)


def pair_label(path_a, path_b, known=None):
    """The pair's label: each path, with when it was last updated (its log's last entry, as known
    (a Replicas), if it is)"""
    return '%s%s <-> %s%s' % (replicanames.labeled(path_a), _updated(known, path_a),
                              replicanames.labeled(path_b), _updated(known, path_b))


def _updated(known, path):
    """' (updated DD.MM.YYYY)' of the replica at path, by its log's last entry, as known has it;
    '' if it doesn't"""
    info = known.info_at(path) if known is not None else None
    date = ((info or {}).get('last_entry') or {}).get('date')
    return ' (updated %s)' % (_date(date),) if date else ''


# What's known of a replica, as it's said (see replicainfo.py)
_date = replicainfo._date
_time = replicainfo._time
FRESH, RECENT, OLD = replicainfo.FRESH, replicainfo.RECENT, replicainfo.OLD
SYNCED_MARK, CACHE_MARK = replicainfo.SYNCED_MARK, replicainfo.CACHE_MARK
freshness = replicainfo.freshness
cache_time = replicainfo.cache_time
path_marks_help = replicainfo.path_marks_help
known_lines = replicainfo.known_lines


def help_lines():
    """The start menu's ? help: what the marks before a pair and its paths are"""
    return (["Marks before a pair: whether it's in sync, as far as dirdelta knows"] +
            ["  " + line for line in syncstate.help_lines()] + path_marks_help())


def styled_pair(label, path_a, path_b, known):
    """A pair's menu label (label, ending with pair_label()'s) as it's shown: after a mark of whether
    it's in sync (see syncstate.py), each path after a mark in the color of when it was last synced
    (grey: never, as far as known), and a Drive one's after one in the color of when Drive's file
    list was read"""
    def marks(path):
        info = known.info_at(path) if known is not None else None
        parts = [(SYNCED_MARK + " ", freshness((info or {}).get('seen')) or 'grey')]
        if paths.is_cloud_path(path):
            parts.append((CACHE_MARK + " ", freshness(cache_time(path)) or 'grey'))
        return parts
    pair = pair_label(path_a, path_b, known)
    head = label[:len(label) - len(pair)] if label.endswith(pair) else label
    a_text = '%s%s' % (replicanames.labeled(path_a), _updated(known, path_a))
    sync_mark, sync_color = syncstate.mark(syncstate.of(known, path_a, path_b))
    return picker.styled([(head, None), (sync_mark + " ", sync_color)] + marks(path_a) + [(a_text + " <-> ", None)] + marks(path_b) +
                         [(pair[len(a_text) + 5:], None)])


def known_paths(replicas):
    """The paths of the replicas known (replicas', a Replicas), each at the path it was last seen at,
    the latest updated first"""
    def last_date(info):
        return ((info.get('last_entry') or {}).get('date') or '', info.get('seen') or '')
    return [(info.get('paths') or [identity])[-1]
            for identity, info in sorted(replicas.known.items(), key=lambda item: last_date(item[1]), reverse=True)]


def _choose_replica(name, known=()):
    """Let the user choose a local dir or a Drive one, or one of known (paths) at once. Returns its
    path, or None if they quit."""
    options = {KNOWN + path: path for path in known}
    where = picker.pick_option(list(options) + [LOCAL, CLOUD], header='Where is %s?' % (name,),
                               title='Choose %s' % (name,))
    if where in options:
        return options[where]
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
