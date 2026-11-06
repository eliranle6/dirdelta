"""The dashboard's rows of each pair and each replica"""
import os

from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashcache
from dirdelta.known import replicainfo
from dirdelta.known import replicalog
from dirdelta.matching import syncstate
from dirdelta.screens.hashes_screen.dashboard_actions import is_there, label_option
from dirdelta.screens.hashes_screen.dashboard_lines import cache_age, drive_lines, job_of
from dirdelta.screens.hashes_screen.names import (BAR, DRIVE, DRIVE_NOTE, FILES, HASH, HEADING,
                                                  HEADING_TEXT, INFO, KNOWN, LABEL, PAIR, PAIR_STATE,
                                                  RESCAN, STATE, TOGGLE, files_text)
from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.util import text


def known_pairs(known):
    """The pairs known (known's favorites, then its history's others), once each"""
    if known is None:
        return []
    found = []
    for pair in known.favorites + known.history:
        if not any(set(pair) == set(other) for other in found):
            found.append(pair)
    return found


def add_pair(path_a, path_b, options, shown, known):
    """The dashboard's lines of a pair: its paths after its sync state's mark, and what its state is
    (see syncstate.py)"""
    state = syncstate.of(known, path_a, path_b)
    mark, color = syncstate.mark(state)
    options += [(PAIR, path_a, path_b), (PAIR_STATE, path_a, path_b)]
    shown[options[-2]] = picker.Skipped(picker.styled([(mark + " ", color), ("%s <-> %s" % (path_a, path_b), 'bold')]))
    shown[options[-1]] = picker.Skipped(picker.styled([("  " + syncstate.describe(state, path_a, path_b), color)]))


def add_replica(item, options, shown, known, names):
    """The dashboard's options of a replica (item: (name, tree or None))"""
    name, tree = item
    job = job_of(name, tree)
    options += [(HEADING, name), (INFO, name)]
    shown[(HEADING, name)] = picker.Skipped(HEADING_TEXT % ("%s: %s" % (names[name], name)
                                                              if names[name] != name else name,))
    info = known.info_at(name) if known is not None else None
    known_lines = replicainfo.known_lines(info, styled=True) if info else ["  Never synced before"]
    if info and not paths.is_cloud_path(name) and not replicalog.is_disk_connected(
            next((identity for identity, other in known.known.items() if other is info), '')):
        known_lines.append("  Its disk isn't connected now")
    for number, line in enumerate(known_lines):
        options.append((KNOWN, number, name))
        shown[options[-1]] = picker.Skipped(line)
    if job is not None:
        options += [(BAR, name), (STATE, name), (TOGGLE, name), (FILES, name), (RESCAN, name)]
    elif isinstance(tree, clouddirtree.CloudDirTree):
        nr_files, size, first, note = drive_lines(tree)
        # When Drive's file list was read, in its freshness's color
        shown[(INFO, name)] = picker.Skipped(picker.styled([
            ("  %s, %s" % (files_text(nr_files), text.format_size(size)), None),
            (cache_age(name), replicainfo.freshness(replicainfo.cache_time(name)))]))
        options += [(DRIVE, name), (DRIVE_NOTE, name)]
        shown[(DRIVE, name)] = picker.Skipped(first)
        shown[(DRIVE_NOTE, name)] = picker.Skipped(note)
    elif paths.is_cloud_path(name):
        shown[(INFO, name)] = picker.Skipped("  In Google Drive: its files and Drive's hashes are "
                                                 "counted when it's synced or sorted")
    else:
        kept = hashcache.count_under(os.path.realpath(name))
        shown[(INFO, name)] = picker.Skipped(
            "  Hashes kept of %s (as of when they were hashed); how many are left is counted when it's "
            "hashed, synced or sorted" % (files_text(kept),))
        options.append((HASH, name))
        shown[(HASH, name)] = ("  Hash its files, in the background" if is_there(name) else
                                picker.Disabled("  Hash its files: its disk isn't mounted"))
    if known is not None:
        options.append((LABEL, name))
        shown[(LABEL, name)] = label_option(name, known)
