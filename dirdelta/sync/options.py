"""The sync menu's lines: whether the two are in sync, and each way's option"""
import concurrent.futures
import time

from dirdelta.known import replicanames
from dirdelta.matching import differing
from dirdelta.matching import syncstate
from dirdelta.sync.way import interactive_dir_sync
from dirdelta.sync.ways import DIFFER, differ_word, files_text
from dirdelta.ui import picker


# The sync menu's first lines: whether the two are in sync (see syncstate.py), as each way finds their
# files; then a point each: the files only in the one, only in the other, and those at the same paths
# that differ
STATE = "Sync state"
STATE_POINTS = ("Sync state: only in A", "Sync state: only in B", "Sync state: differing")


def state_lines(ways, path_a, path_b):
    """{STATE or one of STATE_POINTS: its line (a picker.Skipped)}, by what each way found, the replicas
    by their short names and what each is on (replicanames.told_apart()); while they're found, the
    points are blank"""
    names = replicanames.told_apart([path_a, path_b])
    name_a, name_b = names[path_a], names[path_b]
    found = {point: picker.BLANK for point in STATE_POINTS}
    futures = [way.missing for way in ways]
    if not all(future.done() for future in futures):
        return dict(found, **{STATE: _grey("%s Comparing them..." % (syncstate.MARKS[syncstate.UNKNOWN],))})
    if any(future.exception() is not None for future in futures):
        return dict(found, **{STATE: _grey("%s Couldn't compare them" % (syncstate.MARKS[syncstate.UNKNOWN],))})
    only_a, only_b = [len(future.result().relpaths) for future in futures]
    kind = syncstate.found(only_a, only_b)
    mark, color = syncstate.mark(syncstate.State(kind, only_a, only_b, None, []))
    headline = {syncstate.IN_SYNC: "In sync: each has all the other's files",
                syncstate.A_AHEAD: "%s is ahead of %s" % (name_a, name_b),
                syncstate.B_AHEAD: "%s is ahead of %s" % (name_b, name_a),
                syncstate.BRANCHED: "Branched: each has files the other lacks"}[kind]
    found[STATE] = picker.Skipped(picker.styled([(mark + " " + headline, color)]))
    for point, count, name in zip(STATE_POINTS, (only_a, only_b), (name_a, name_b)):
        found[point] = _point([("%s only in %s" % (files_text(count) if count else "None", name), None)])
    differ = ways[0].differs
    if differ is None or not differ.done():
        found[STATE_POINTS[2]] = _point([("Files at the same paths: comparing them...", 'grey')])
    elif differ.exception() is not None:
        found[STATE_POINTS[2]] = _point([("Files at the same paths: couldn't compare them", 'grey')])
    else:
        nr_differ = len(differ.result())
        found[STATE_POINTS[2]] = _point([("%s at the same paths %s" % (files_text(nr_differ), differ_word(nr_differ))
                                          if nr_differ else "None at the same paths differ", differing.STYLE if nr_differ else None)])
    return found


def _grey(text):
    return picker.Skipped(picker.styled([(text, 'grey')]))


def _point(parts):
    """A line of the sync state's, as a bullet point under it"""
    return picker.Skipped(picker.styled([("  \u2022 ", None)] + parts))


# The sync menu's option of the combined tree (sync/combined/), the first
SYNC_ALL = "Sync: all the differences in one tree"


def sync_all_shown_as(ways, path_a, path_b):
    """SYNC_ALL's label, with how many files it shows of each (or that they're still being found);
    with none, it can't be picked"""
    futures = [way.missing for way in ways] + [ways[0].differs]
    if not all(future is not None and future.done() for future in futures):
        dots = int(time.monotonic() / DOTS_INTERVAL) % 4
        return "%s (loading%s)" % (SYNC_ALL, '.' * dots)
    if any(future.exception() is not None for future in futures):
        return "%s (couldn't compare them)" % (SYNC_ALL,)
    names = replicanames.short_names([path_a, path_b])
    only_a, only_b, differ = [len(future.result().relpaths) for future in futures[:2]] + [len(futures[2].result())]
    if not (only_a or only_b or differ):
        return picker.Disabled("%s: nothing differs" % (SYNC_ALL,))
    parts = (["%d only in %s" % (only_a, names[path_a])] if only_a else []) + (
        ["%d only in %s" % (only_b, names[path_b])] if only_b else []) + (
        ["%d %s" % (differ, differ_word(differ))] if differ else [])
    return "%s (%s)" % (SYNC_ALL, ", ".join(parts))


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
        # (Named for what it shows: e.g. 'Only in eliran on LocalDisk(07B)', the files the other lacks)
        only_in = replicanames.told_apart([self.src_path, self.dst_path])[self.src_path]
        with picker.place(DIFFER if self.only_differing else "Only in %s" % (only_in,)):
            sync.browse()
        self.was_read_anew = sync.was_read_anew
        return sync.has_changed
