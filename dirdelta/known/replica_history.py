"""What's known of the replicas (Replicas): the pairs synced, the favorites, the sorts, each sorted tree's recent dirs, each replica's last entry and labels"""
from dirdelta.trees import paths


# How many pairs the history keeps, and how many inbox sorts
MAX_HISTORY = 20
MAX_SORTS = 10
# How many of a sorted tree's dirs are kept as its recent ones
MAX_RECENT_DIRS = 10
# How many of the paths a replica was seen at are kept
MAX_PATHS_KEPT = 5


# One way for all (see paths.normalized())
normalized = paths.normalized


class Replicas(object):
    def __init__(self, history=None, favorites=None, sorts=None, recent_dirs=None, known=None, compared=None,
                 labels=None):
        # Pairs (tuples of 2 normalized paths), the latest first
        self.history = list(history or [])
        # Pairs, in the order they were added
        self.favorites = list(favorites or [])
        # (inbox, sorted tree) pairs (normalized), the latest first
        self.sorts = list(sorts or [])
        # {a sorted tree's path (normalized): its dirs' relpaths ('' its root) files went to, the
        # latest first}
        self.recent_dirs = {root: list(dirs) for root, dirs in (recent_dirs or {}).items()}
        # {a replica's identity (replicalog.identity()): {'paths': the paths it was seen at (the
        # latest first), 'last_entry': its log's last entry ({'date': 'YYYY-MM-DD' or None, 'text'}),
        # or None, 'seen': when dirdelta last synced it, 'changed': when a sync last changed it (or
        # None); times as 'YYYY-MM-DD HH:MM'}}
        self.known = {identity: dict(info) for identity, info in (known or {}).items()}
        # Of each pair a sync compared, the latest first: {'pair': [path_a, path_b] (normalized),
        # 'only': [how many of a's files b lacked, how many of b's a lacked], 'when': 'YYYY-MM-DD
        # HH:MM'}
        self.compared = [dict(item) for item in (compared or [])]
        # {what a label is of (replicanames.label_key()): the label the user gave it}
        self.labels = dict(labels or {})

    def set_label(self, key, label):
        """Label what key is of (None: it has no label now)"""
        if label:
            self.labels[key] = label
        else:
            self.labels.pop(key, None)

    def note_compared(self, path_a, path_b, only_a, only_b, when):
        """Note that a sync just found (when, a datetime) that a had only_a files b lacked, and b
        only_b that a lacked"""
        pair = _pair(path_a, path_b)
        self.compared = [{'pair': list(pair), 'only': [only_a, only_b], 'when': _time(when)}] + [
            old for old in self.compared if not _is_same_pair(old['pair'], pair)]
        del self.compared[MAX_HISTORY + len(self.favorites):]

    def comparison(self, path_a, path_b):
        """What a sync last found of the pair, a's first: {'only': [a's files b lacked, b's a lacked],
        'when': 'YYYY-MM-DD HH:MM'}; or None if it was never compared"""
        pair = _pair(path_a, path_b)
        for item in self.compared:
            if _is_same_pair(item['pair'], pair):
                only = item['only'] if tuple(item['pair']) == pair else list(reversed(item['only']))
                return {'only': list(only), 'when': item['when']}
        return None

    def note_seen(self, identity, path, entry, when):
        """Note that the replica with identity was just synced at path (when, a datetime), with its
        log's last entry (a replicalog.Entry, or None if it has none, or it couldn't be read: the
        one kept stays)"""
        info = self.known.setdefault(identity, {'paths': [], 'last_entry': None, 'seen': None, 'changed': None})
        path = normalized(path)
        info['paths'] = ([path] + [old for old in info['paths'] if old != path])[:MAX_PATHS_KEPT]
        if entry is not None:
            info['last_entry'] = {'date': entry.date.isoformat() if entry.date else None, 'text': entry.text}
        info['seen'] = _time(when)

    def note_changed(self, identity, when):
        """Note that a sync just changed the replica with identity (when, a datetime)"""
        info = self.known.setdefault(identity, {'paths': [], 'last_entry': None, 'seen': None, 'changed': None})
        info['changed'] = _time(when)

    def note_entry(self, identity, entry):
        """Note that the log of the replica with identity has entry last now (a replicalog.Entry)"""
        info = self.known.setdefault(identity, {'paths': [], 'last_entry': None, 'seen': None, 'changed': None})
        info['last_entry'] = {'date': entry.date.isoformat() if entry.date else None, 'text': entry.text}

    def info_at(self, path):
        """What's known of the replica last seen at path (the latest seen, if several were), or
        None"""
        path = normalized(path)
        found = [info for info in self.known.values() if path in info.get('paths', [])]
        return max(found, key=lambda info: info.get('seen') or '') if found else None

    def record_dir(self, root_path, relpath):
        """Note that files were just moved or copied to the dir at relpath in the sorted tree at
        root_path: it goes to the top of its recent dirs (once)"""
        root = normalized(root_path)
        self.recent_dirs[root] = [relpath] + [old for old in self.recent_dirs.get(root, []) if old != relpath]
        del self.recent_dirs[root][MAX_RECENT_DIRS:]

    def dirs_of(self, root_path):
        """The sorted tree's recent dirs, the latest first"""
        return list(self.recent_dirs.get(normalized(root_path), []))

    def record_sort(self, inbox_path, root_path):
        """Note that the inbox was just sorted into root_path: it goes to the top of the sorts (once;
        the other way around is another sort)"""
        sort = _pair(inbox_path, root_path)
        self.sorts = [sort] + [old for old in self.sorts if old != sort]
        del self.sorts[MAX_SORTS:]

    def record(self, path_a, path_b):
        """Note that the pair was just synced: it goes to the top of the history (once)"""
        pair = _pair(path_a, path_b)
        self.history = [pair] + [old for old in self.history if not _is_same_pair(old, pair)]
        del self.history[MAX_HISTORY:]

    def is_favorite(self, path_a, path_b):
        pair = _pair(path_a, path_b)
        return any(_is_same_pair(favorite, pair) for favorite in self.favorites)

    def toggle_favorite(self, path_a, path_b):
        """Make the pair a favorite, or, if it is one, not"""
        pair = _pair(path_a, path_b)
        if self.is_favorite(*pair):
            self.favorites = [old for old in self.favorites if not _is_same_pair(old, pair)]
        else:
            self.favorites.append(pair)

    def recent(self):
        """The history's pairs that aren't favorites (which are shown on their own)"""
        return [pair for pair in self.history if not self.is_favorite(*pair)]


def _pair(path_a, path_b):
    return (normalized(path_a), normalized(path_b))


def _is_same_pair(pair, other):
    return set(pair) == set(other)


def _time(when):
    return when.strftime('%Y-%m-%d %H:%M')
