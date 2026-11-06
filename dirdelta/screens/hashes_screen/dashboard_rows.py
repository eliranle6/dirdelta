"""The dashboard's rows of each pair and each replica"""
import os

from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashcache
from dirdelta.known import replicainfo
from dirdelta.known import replicalog
from dirdelta.matching import syncstate
from dirdelta.screens.hashes_screen.dashboard_actions import _is_there, _label_option
from dirdelta.screens.hashes_screen.dashboard_lines import _cache_age, _drive_lines, _job_of
from dirdelta.screens.hashes_screen.names import (_BAR,
    _DRIVE,
    _DRIVE_NOTE,
    _FILES,
    _HASH,
    _HEADING,
    _HEADING_TEXT,
    _INFO,
    _KNOWN,
    _LABEL,
    _PAIR,
    _PAIR_STATE,
    _RESCAN,
    _STATE,
    _TOGGLE,
    _files)
from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.util import text


def _pairs(known):
    """The pairs known (known's favorites, then its history's others), once each"""
    if known is None:
        return []
    found = []
    for pair in known.favorites + known.history:
        if not any(set(pair) == set(other) for other in found):
            found.append(pair)
    return found


def _add_pair(path_a, path_b, options, shown, known):
    """The dashboard's lines of a pair: its paths after its sync state's mark, and what its state is
    (see syncstate.py)"""
    state = syncstate.of(known, path_a, path_b)
    mark, color = syncstate.mark(state)
    options += [(_PAIR, path_a, path_b), (_PAIR_STATE, path_a, path_b)]
    shown[options[-2]] = picker.Skipped(picker.styled([(mark + " ", color), ("%s <-> %s" % (path_a, path_b), 'bold')]))
    shown[options[-1]] = picker.Skipped(picker.styled([("  " + syncstate.describe(state, path_a, path_b), color)]))


def _add_replica(item, options, shown, known, names):
    """The dashboard's options of a replica (item: (name, tree or None))"""
    name, tree = item
    job = _job_of(name, tree)
    options += [(_HEADING, name), (_INFO, name)]
    shown[(_HEADING, name)] = picker.Skipped(_HEADING_TEXT % ("%s: %s" % (names[name], name)
                                                              if names[name] != name else name,))
    info = known.info_at(name) if known is not None else None
    known_lines = replicainfo.known_lines(info, styled=True) if info else ["  Never synced before"]
    if info and not paths.is_cloud_path(name) and not replicalog.is_disk_connected(
            next((identity for identity, other in known.known.items() if other is info), '')):
        known_lines.append("  Its disk isn't connected now")
    for number, line in enumerate(known_lines):
        options.append((_KNOWN, number, name))
        shown[options[-1]] = picker.Skipped(line)
    if job is not None:
        options += [(_BAR, name), (_STATE, name), (_TOGGLE, name), (_FILES, name), (_RESCAN, name)]
    elif isinstance(tree, clouddirtree.CloudDirTree):
        nr_files, size, first, note = _drive_lines(tree)
        # When Drive's file list was read, in its freshness's color
        shown[(_INFO, name)] = picker.Skipped(picker.styled([
            ("  %s, %s" % (_files(nr_files), text.format_size(size)), None),
            (_cache_age(name), replicainfo.freshness(replicainfo.cache_time(name)))]))
        options += [(_DRIVE, name), (_DRIVE_NOTE, name)]
        shown[(_DRIVE, name)] = picker.Skipped(first)
        shown[(_DRIVE_NOTE, name)] = picker.Skipped(note)
    elif paths.is_cloud_path(name):
        shown[(_INFO, name)] = picker.Skipped("  In Google Drive: its files and Drive's hashes are "
                                                 "counted when it's synced or sorted")
    else:
        kept = hashcache.count_under(os.path.realpath(name))
        shown[(_INFO, name)] = picker.Skipped(
            "  Hashes kept of %s (as of when they were hashed); how many are left is counted when it's "
            "hashed, synced or sorted" % (_files(kept),))
        options.append((_HASH, name))
        shown[(_HASH, name)] = ("  Hash its files, in the background" if _is_there(name) else
                                picker.Disabled("  Hash its files: its disk isn't mounted"))
    if known is not None:
        options.append((_LABEL, name))
        shown[(_LABEL, name)] = _label_option(name, known)
