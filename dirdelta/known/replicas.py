"""The pairs of replicas the user synced (history, the latest first) and the ones they made favorites,
and the inboxes they sorted (each with its sorted tree, see inbox.py), kept in the user's REPLICAS_FILE (JSON, see users.py)
for the menu that chooses what to sync or sort (see choose_replicas.py); the dirs of each sorted
tree that its inboxes' files were moved or copied to last, offered first next time, and its other
replicas a sort was asked to copy them into too; and what's known
of each replica synced (see replicalog.py), by its identity: the paths it was seen at, its log's
last entry, and when dirdelta last saw it and changed it; and of each pair, what a sync last found
each had that the other lacked (see syncstate.py).

A pair is the same pair either way around (A and B, or B and A), and is kept the way around it was
last used. Local paths are kept absolute and cloud ones cleaned (see normalized()), so the same dir
typed twice differently is one pair.

The file is this module's (load(), save()); what's kept in it is replica_history.py's."""
import copy
import json
import os
import threading

from dirdelta.known import users
from dirdelta.known.replica_history import Replicas, pair_of, normalized
from dirdelta.known.replica_history import MAX_HISTORY, MAX_PATHS_KEPT, MAX_RECENT_DIRS, MAX_SORTS  # noqa: F401

# The owner's (another user's is in a folder of theirs beside it: replicas_file(), see users.py)
REPLICAS_FILE = os.path.expanduser('~/.config/dirdelta/replicas.json')


class ReplicasError(Exception):
    pass


# (One save at a time: each reads the file, then writes it)
_saving = threading.Lock()


def replicas_file():
    """The current user's file"""
    return users.own(REPLICAS_FILE)


def load():
    """The current user's Replicas (none if there's no file yet), knowing what the file had (see save())"""
    path = replicas_file()
    try:
        with open(path) as opened:
            content = json.load(opened)
        found = _from(content)
    except FileNotFoundError:
        found = Replicas()
    except (OSError, ValueError, AttributeError, TypeError) as error:
        # Not overwritten with an empty one: it may be favorites edited by hand, with a typo
        raise ReplicasError("Cannot read %s (fix or remove it): %s" % (path, error))
    found.as_read = copy.deepcopy(_content(found))
    return found


def _from(content):
    """The Replicas of what the file has (content, its JSON)"""
    return Replicas(_pairs(content.get('history', [])), _pairs(content.get('favorites', [])),
                    _pairs(content.get('sorts', [])), _recent_dirs(content.get('recent_dirs', {})),
                    _known(content.get('known', {})), _compared(content.get('compared', [])),
                    {str(key): str(label) for key, label in content.get('labels', {}).items()},
                    _followers(content.get('followers', {})), _paths(content.get('replicas', [])),
                    _paths(content.get('inboxes', [])),
                    {str(key): dict(look) for key, look in content.get('looks', {}).items() if isinstance(look, dict)},
                    content.get('main') or None, _pairs(content.get('pairs', [])))


def save(replicas):
    """Write replicas to the current user's file, replacing it at once (so it's never half-written). What it
    didn't change since it was loaded is the file's as it is now: what another one saved meanwhile stays (e.g. a
    replica named on the web page while a sync that loaded the file before goes on, and saves what it compared)"""
    path = replicas_file()
    with _saving:
        content = _content(replicas)
        as_read = getattr(replicas, 'as_read', None)
        if as_read is not None:
            try:
                with open(path) as opened:
                    now = _content(_from(json.load(opened)))
            except FileNotFoundError:
                now = None
            except (OSError, ValueError, AttributeError, TypeError) as error:
                raise ReplicasError("Cannot read %s (fix or remove it): %s" % (path, error))
            if now is not None:
                content = {key: now[key] if value == as_read.get(key) else value for key, value in content.items()}
                # (And it has them too, from now on)
                replicas.__dict__.update(_from(content).__dict__)
        _write(path, content)
        # (A copy: what it has changes as it's changed)
        replicas.as_read = copy.deepcopy(content)


def _content(replicas):
    """What the file has of replicas (its JSON)"""
    return {'favorites': [list(pair) for pair in replicas.favorites],
               'history': [list(pair) for pair in replicas.history],
               'sorts': [list(pair) for pair in replicas.sorts],
               'recent_dirs': replicas.recent_dirs,
               'known': replicas.known,
               'compared': replicas.compared,
               'labels': replicas.labels,
               'followers': replicas.followers,
               'replicas': replicas.added_replicas,
               'inboxes': replicas.added_inboxes,
               'looks': replicas.looks,
               'main': replicas.main_replica,
               'pairs': [list(pair) for pair in replicas.extra_pairs]}


def _write(path, content):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = path + '.tmp'
        with open(temp_path, 'w') as opened:
            json.dump(content, opened, indent=2)
            opened.write('\n')
        os.replace(temp_path, path)
    except OSError as error:
        raise ReplicasError("Cannot write %s: %s" % (path, error))


def _paths(items):
    """A list of paths read from the file"""
    if not (isinstance(items, list) and all(isinstance(path, str) for path in items)):
        raise ValueError("not a list of paths: %r" % (items,))
    return list(items)


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


def _followers(content):
    """The sorted trees' other replicas read from the file: {a sorted tree's path: [paths]}"""
    if not isinstance(content, dict) or not all(
            isinstance(found, list) and all(isinstance(path, str) for path in found) for found in content.values()):
        raise ValueError("not sorted trees' other replicas: %r" % (content,))
    return {normalized(root): [normalized(path) for path in found] for root, found in content.items()}


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
