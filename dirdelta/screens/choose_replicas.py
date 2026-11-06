"""The menu that chooses what to sync, when dirdelta is run without paths: a replica for each of its
two slots (a local dir under /, or a Drive one), or a favorite or recent pair at once; or an inbox
to sort into a sorted tree (inbox.py), a new one or a recent one. Each kind is a section of its own,
under a heading."""
import os

from dirdelta.hashes import hashing
from dirdelta.screens import hashes_screen
from dirdelta.screens.pair_labels import (favorite_label, help_lines, known_paths, recent_label, slot_label,
                                          sort_label, styled_pair)
from dirdelta.screens.replica_choices import _choose_replica, known_replicas
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.screens.start_names import (CLOUD, KNOWN_LIST, LOCAL, NOT_CHOSEN, QUIT,  # noqa: F401
                                          RECENT_SORTS_SECTION, RECENT_SYNCS_SECTION, REPLICAS_SECTION, SORT,
                                          SORT_SECTION, SYNC_SECTION, Sort)


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
                                    selected=('slot', 0), help_lines=help_lines(),
                                    shown_as=hashes_screen.hashing_status if hashing.jobs() else None)
        if option in (None, QUIT):
            if hashes_screen.is_ok_to_quit():
                return None
            continue
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
