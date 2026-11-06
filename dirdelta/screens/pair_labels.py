"""How the start menu labels pairs, sorts and replicas: their names, when each was updated, and their marks"""
from dirdelta.known import replicainfo
from dirdelta.known import replicanames
from dirdelta.matching import syncstate
from dirdelta.screens.start_names import NOT_CHOSEN
from dirdelta.trees import paths
from dirdelta.ui import picker


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
