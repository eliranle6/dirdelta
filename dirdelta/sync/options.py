"""The sync menu's lines: whether the two are in sync, and each way's option"""
import concurrent.futures
import time

from dirdelta.known import replicanames
from dirdelta.matching import differing
from dirdelta.matching import syncstate
from dirdelta.sync.way import interactive_dir_sync
from dirdelta.sync.ways import DIFFER, differ_word, files_text
from dirdelta.ui import picker


# The sync menu's first line: whether the two are in sync (see syncstate.py), as each way finds
# their files
STATE = "Sync state"


def state_line(ways, path_a, path_b):
    """The sync menu's line of whether the two are in sync, by what each way found (a
    picker.Skipped), the replicas by their short names (the breadcrumbs')"""
    names = replicanames.short_names([path_a, path_b])
    path_a, path_b = names[path_a], names[path_b]
    futures = [way.missing for way in ways]
    if not all(future.done() for future in futures):
        return picker.Skipped(picker.styled([("%s Comparing them..." % (syncstate.MARKS[syncstate.UNKNOWN],), 'grey')]))
    if any(future.exception() is not None for future in futures):
        return picker.Skipped(picker.styled([("%s Couldn't compare them" % (syncstate.MARKS[syncstate.UNKNOWN],), 'grey')]))
    only_a, only_b = [len(future.result().relpaths) for future in futures]
    state = syncstate.State(syncstate.found(only_a, only_b), only_a, only_b, None, [])
    mark, color = syncstate.mark(state)
    differ = ways[0].differs
    nr_differ = len(differ.result()) if differ.done() and differ.exception() is None else 0
    return picker.Skipped(picker.styled([(mark + " ", color), (syncstate.describe(state, path_a, path_b), color),
                                         ("; %s at the same paths %s" % (files_text(nr_differ), differ_word(nr_differ)) if nr_differ else "",
                                          differing.STYLE)]))


# How often the "loading" dots of a menu option change, in seconds
DOTS_INTERVAL = 0.4


class Action(object):
    """A main menu option: the files of a way (interactive_dir_sync), from the replica at src_path to
    the one at dst_path. Their names are worked out each time, as a replica may be labeled meanwhile."""
    def __init__(self, src_path, dst_path, way, changes=None, only_differing=False):
        """With only_differing, it's the files that differ only (see DIFFER)"""
        self.src_path = src_path
        self.dst_path = dst_path
        self.way = way
        self.changes = changes
        self.only_differing = only_differing

    def shown_as(self):
        """The label, with how many files it's about, or that they're still being found. With none,
        it can't be picked (a picker.Disabled): it would only say so. Once the files are found
        again (after a live action), it may be picked again."""
        if self.only_differing:
            label = "%s at the same paths in both" % (DIFFER,)
        else:
            label = "Files only in %s" % (replicanames.full(self.src_path),)
        missing, differs = self.way.missing, self.way.differs
        if differs is None:
            # Not looked for
            differs = concurrent.futures.Future()
            differs.set_result({})
        if not missing.done() or (self.only_differing and not differs.done()):
            dots = int(time.monotonic() / DOTS_INTERVAL) % 4
            return "%s (loading%s)" % (label, '.' * dots)
        nr_differ = len(differs.result()) if differs.done() and differs.exception() is None else 0
        if self.only_differing:
            if differs.exception() is not None:
                return "%s (couldn't compare them)" % (label,)
            if nr_differ == 0:
                return picker.Disabled("%s: none" % (label,))
            return "%s (%s)" % (label, files_text(nr_differ))
        if missing.exception() is not None:
            return "%s (couldn't count the files)" % (label,)
        count = len(missing.result().relpaths)
        # The ones that differ are in its picker too
        and_differ = ", and %d that %s" % (nr_differ, differ_word(nr_differ)) if nr_differ else ""
        if count == 0 and not nr_differ:
            return picker.Disabled("%s: none, %s has them all" % (label, replicanames.full(self.dst_path)))
        return "%s (%s%s)" % (label, files_text(count), and_differ)

    def run(self):
        """Returns whether the replicas' files changed meanwhile (see InteractiveDirSync)"""
        way = self.way
        sync = interactive_dir_sync.InteractiveDirSync(way.src, way.dst, way.missing,
                                                       way.indexes[way.src], way.indexes[way.dst],
                                                       way.checked, self.changes, way.differs,
                                                       self.only_differing, way.compared)
        with picker.place(DIFFER if self.only_differing else "Files in %s" % (replicanames.full(self.src_path),)):
            sync.browse()
        self.was_read_anew = sync.was_read_anew
        return sync.has_changed
