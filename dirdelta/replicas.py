"""The pairs of replicas the user synced (history, the latest first) and the ones they made favorites,
kept in REPLICAS_FILE (JSON) for the menu that chooses what to sync (see choose_replicas.py).

A pair is the same pair either way around (A and B, or B and A), and is kept the way around it was
last used. Local paths are kept absolute and cloud ones cleaned (see normalized()), so the same dir
typed twice differently is one pair."""
import json
import os

from dirdelta import paths

REPLICAS_FILE = os.path.expanduser('~/.config/dirdelta/replicas.json')

# How many pairs the history keeps
MAX_HISTORY = 20


class ReplicasError(Exception):
    pass


def normalized(path):
    """path as it's kept: a cloud path cleaned ('cloud//mein/' is 'cloud/mein'), a local one
    absolute and without a trailing '/'"""
    if paths.is_cloud_path(path):
        return '/'.join(paths.components(path))
    return os.path.abspath(path)


class Replicas(object):
    def __init__(self, history=None, favorites=None):
        # Pairs (tuples of 2 normalized paths), the latest first
        self.history = list(history or [])
        # Pairs, in the order they were added
        self.favorites = list(favorites or [])

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


def load():
    """The Replicas in REPLICAS_FILE (none if there's no file yet)"""
    try:
        with open(REPLICAS_FILE) as replicas_file:
            content = json.load(replicas_file)
        return Replicas(_pairs(content.get('history', [])), _pairs(content.get('favorites', [])))
    except FileNotFoundError:
        return Replicas()
    except (OSError, ValueError, AttributeError, TypeError) as error:
        # Not overwritten with an empty one: it may be favorites edited by hand, with a typo
        raise ReplicasError("Cannot read %s (fix or remove it): %s" % (REPLICAS_FILE, error))


def save(replicas):
    """Write replicas to REPLICAS_FILE, replacing it at once (so it's never half-written)"""
    content = {'favorites': [list(pair) for pair in replicas.favorites],
               'history': [list(pair) for pair in replicas.history]}
    try:
        os.makedirs(os.path.dirname(REPLICAS_FILE), exist_ok=True)
        temp_path = REPLICAS_FILE + '.tmp'
        with open(temp_path, 'w') as replicas_file:
            json.dump(content, replicas_file, indent=2)
            replicas_file.write('\n')
        os.replace(temp_path, REPLICAS_FILE)
    except OSError as error:
        raise ReplicasError("Cannot write %s: %s" % (REPLICAS_FILE, error))


def _pair(path_a, path_b):
    return (normalized(path_a), normalized(path_b))


def _is_same_pair(pair, other):
    return set(pair) == set(other)


def _pairs(items):
    """The pairs in a list read from the file: each a list of 2 paths"""
    pairs = []
    for item in items:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(path, str) for path in item)):
            raise ValueError("not a pair of paths: %r" % (item,))
        pairs.append(_pair(*item))
    return pairs
