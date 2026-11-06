"""The pairs of replicas the user synced (history, the latest first) and the ones they made favorites,
and the inboxes they sorted (each with its sorted tree, see inbox.py), kept in REPLICAS_FILE (JSON)
for the menu that chooses what to sync or sort (see choose_replicas.py); the dirs of each sorted
tree that its inboxes' files were moved or copied to last, offered first next time; and what's known
of each replica synced (see replicalog.py), by its identity: the paths it was seen at, its log's
last entry, and when dirdelta last saw it and changed it; and of each pair, what a sync last found
each had that the other lacked (see syncstate.py).

A pair is the same pair either way around (A and B, or B and A), and is kept the way around it was
last used. Local paths are kept absolute and cloud ones cleaned (see normalized()), so the same dir
typed twice differently is one pair.

The file is this module's (load(), save()); what's kept in it is replica_history.py's."""
import json
import os

from dirdelta.known.replica_history import Replicas, pair_of, normalized
from dirdelta.known.replica_history import MAX_HISTORY, MAX_PATHS_KEPT, MAX_RECENT_DIRS, MAX_SORTS  # noqa: F401

REPLICAS_FILE = os.path.expanduser('~/.config/dirdelta/replicas.json')


class ReplicasError(Exception):
    pass


def load():
    """The Replicas in REPLICAS_FILE (none if there's no file yet)"""
    try:
        with open(REPLICAS_FILE) as replicas_file:
            content = json.load(replicas_file)
        return Replicas(_pairs(content.get('history', [])), _pairs(content.get('favorites', [])),
                        _pairs(content.get('sorts', [])), _recent_dirs(content.get('recent_dirs', {})),
                        _known(content.get('known', {})), _compared(content.get('compared', [])),
                        {str(key): str(label) for key, label in content.get('labels', {}).items()})
    except FileNotFoundError:
        return Replicas()
    except (OSError, ValueError, AttributeError, TypeError) as error:
        # Not overwritten with an empty one: it may be favorites edited by hand, with a typo
        raise ReplicasError("Cannot read %s (fix or remove it): %s" % (REPLICAS_FILE, error))


def save(replicas):
    """Write replicas to REPLICAS_FILE, replacing it at once (so it's never half-written)"""
    content = {'favorites': [list(pair) for pair in replicas.favorites],
               'history': [list(pair) for pair in replicas.history],
               'sorts': [list(pair) for pair in replicas.sorts],
               'recent_dirs': replicas.recent_dirs,
               'known': replicas.known,
               'compared': replicas.compared,
               'labels': replicas.labels}
    try:
        os.makedirs(os.path.dirname(REPLICAS_FILE), exist_ok=True)
        temp_path = REPLICAS_FILE + '.tmp'
        with open(temp_path, 'w') as replicas_file:
            json.dump(content, replicas_file, indent=2)
            replicas_file.write('\n')
        os.replace(temp_path, REPLICAS_FILE)
    except OSError as error:
        raise ReplicasError("Cannot write %s: %s" % (REPLICAS_FILE, error))


def _pairs(items):
    """The pairs in a list read from the file: each a list of 2 paths"""
    pairs = []
    for item in items:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(path, str) for path in item)):
            raise ValueError("not a pair of paths: %r" % (item,))
        pairs.append(pair_of(*item))
    return pairs


def _recent_dirs(content):
    """The recent dirs read from the file: {a sorted tree's path: [relpaths]}"""
    if not isinstance(content, dict) or not all(
            isinstance(dirs, list) and all(isinstance(relpath, str) for relpath in dirs) for dirs in content.values()):
        raise ValueError("not sorted trees' recent dirs: %r" % (content,))
    return {normalized(root): dirs for root, dirs in content.items()}


def _known(content):
    """What's known of the replicas, as read from the file: {identity: {'paths': [...], ...}}"""
    if not isinstance(content, dict) or not all(
            isinstance(info, dict) and isinstance(info.get('paths', []), list) for info in content.values()):
        raise ValueError("not what's known of the replicas: %r" % (content,))
    return content


def _compared(content):
    """The pairs compared, as read from the file: [{'pair': [a, b], 'only': [n, m], 'when': ...}]"""
    if not isinstance(content, list) or not all(
            isinstance(item, dict) and len(item.get('pair') or []) == 2 and len(item.get('only') or []) == 2 and
            isinstance(item.get('when'), str) for item in content):
        raise ValueError("not the pairs compared: %r" % (content,))
    return [dict(item, pair=list(pair_of(*item['pair']))) for item in content]
