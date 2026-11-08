"""The combined tree's entries (each difference between the replicas, in a group), their states (what
to do with each), and the plan the states make"""
import collections

from dirdelta.sync import replica_ops
from dirdelta.ui import picker

# The entries' groups: the files only in A, only in B, the ones both have that differ, and the moved
# pairs (a file only in A and one only in B with the same contents: see moved.py), shown at A's path
ONLY_A, ONLY_B, DIFFER, MOVED = 'only-a', 'only-b', 'differ', 'moved'

# The states: nothing, make B like A (copy A's file to B, A's version over B's, or remove B's), make
# A like B (a moved pair: moving B's file to A's path, or A's to B's). Each entry allows the ones its replica can be changed by.
SKIP, TO_B, TO_A = 'skip', 'to-b', 'to-a'
# Their keys (none of treepicker's)
SKIP_KEY, TO_B_KEY, TO_A_KEY = 's', '>', '<'
# The arrows say which way the files go; a removal is a red x
COPY_COLOR, REMOVE_MARK, REMOVE_COLOR, REPLACE_COLOR, MOVE_COLOR = 'green', 'x', 'red', 'yellow', 'cyan'
STATES = [picker.State(SKIP, ' ', 'grey', SKIP_KEY),
          picker.State(TO_B, '⇒', 'blue', TO_B_KEY, {ONLY_A: ('⇒', COPY_COLOR), ONLY_B: (REMOVE_MARK, REMOVE_COLOR),
                                                     DIFFER: ('⇒', REPLACE_COLOR), MOVED: ('⇒', MOVE_COLOR)}),
          picker.State(TO_A, '⇐', 'blue', TO_A_KEY, {ONLY_A: (REMOVE_MARK, REMOVE_COLOR), ONLY_B: ('⇐', COPY_COLOR),
                                                     DIFFER: ('⇐', REPLACE_COLOR), MOVED: ('⇐', MOVE_COLOR)})]

# What the states make: the relpaths of each of the things done (the moves: (relpath, new_relpath))
Plan = collections.namedtuple('Plan', ['copy_to_b', 'copy_to_a', 'replace_b', 'replace_a', 'remove_from_a',
                                       'remove_from_b', 'move_in_b', 'move_in_a'], defaults=((), ()))


def groups(only_a, only_b, changes, moved=None):
    """{relpath: its group}: only_a's, only_b's (relpaths) and changes' (differing.Changes, A's way);
    moved's pairs ({relpath only in A: relpath only in B}) in MOVED, at A's path (B's isn't in it)"""
    moved = moved or {}
    in_b = set(moved.values())
    grouped = {relpath: MOVED if relpath in moved else ONLY_A for relpath in only_a}
    grouped.update((relpath, ONLY_B) for relpath in only_b if relpath not in in_b)
    grouped.update((relpath, DIFFER) for relpath in changes)
    return grouped


def allowed(replica_a, replica_b):
    """{group: the states its entries allow}: making B like A changes B (copying into it, or removing
    from it), and the other way A, so each is allowed only if it can be done (see replica_ops)"""
    to_b_copy, to_a_copy = replica_ops.can_copy(replica_a, replica_b), replica_ops.can_copy(replica_b, replica_a)
    writable_a, writable_b = replica_ops.is_writable(replica_a), replica_ops.is_writable(replica_b)

    def states(to_b, to_a):
        return (SKIP,) + ((TO_B,) if to_b else ()) + ((TO_A,) if to_a else ())
    return {ONLY_A: states(to_b_copy, writable_a), ONLY_B: states(writable_b, to_a_copy),
            DIFFER: states(to_b_copy, to_a_copy), MOVED: states(writable_b, writable_a)}


def entries(grouped, allowed_states, chosen=None):
    """The picker's entries (picker.StateEntry) of grouped ({relpath: group}), each dir's together, in
    the state chosen for it before ({relpath: state}), if any"""
    chosen = chosen or {}
    return [picker.StateEntry(relpath, group, allowed_states[group], chosen.get(relpath, ''))
            for relpath, group in sorted(grouped.items(), key=lambda item: item[0].split('/'))]


def plan_of(chosen, grouped, moved=None):
    """The Plan of the states chosen ({relpath: state}, of grouped's relpaths; moved: the moved pairs,
    as groups()'s)"""
    moved = moved or {}
    things = {name: [] for name in Plan._fields}
    by_state = {(ONLY_A, TO_B): 'copy_to_b', (ONLY_A, TO_A): 'remove_from_a',
                (ONLY_B, TO_A): 'copy_to_a', (ONLY_B, TO_B): 'remove_from_b',
                (DIFFER, TO_B): 'replace_b', (DIFFER, TO_A): 'replace_a'}
    for relpath in sorted(chosen, key=lambda relpath: relpath.split('/')):
        group, state = grouped.get(relpath), chosen[relpath]
        if group == MOVED and relpath in moved:
            # B's file to A's path, or A's to B's
            if state == TO_B:
                things['move_in_b'].append((moved[relpath], relpath))
            elif state == TO_A:
                things['move_in_a'].append((relpath, moved[relpath]))
            continue
        thing = by_state.get((group, state))
        if thing is not None:
            things[thing].append(relpath)
    return Plan(**things)


def is_empty(plan):
    return not any(plan)


def removals(plan):
    """How many files the plan removes (from either replica)"""
    return len(plan.remove_from_a) + len(plan.remove_from_b)


def summary(plan, name_a, name_b):
    """What the plan does, in the order it's done (see doing.py): [(a line, its files' lines)], e.g.
    ("Copy 3 files from A to B", ["photos/a.jpg", ...])"""
    things = [(plan.move_in_b, "Move {files} in %s to where %s has them" % (name_b, name_a)),
              (plan.move_in_a, "Move {files} in %s to where %s has them" % (name_a, name_b)),
              (plan.copy_to_b, "Copy {files} from %s to %s" % (name_a, name_b)),
              (plan.copy_to_a, "Copy {files} from %s to %s" % (name_b, name_a)),
              (plan.replace_b, "Replace %s's versions of {files} with %s's" % (name_b, name_a)),
              (plan.replace_a, "Replace %s's versions of {files} with %s's" % (name_a, name_b)),
              (plan.remove_from_a, "Remove {files} from %s" % (name_a,)),
              (plan.remove_from_b, "Remove {files} from %s" % (name_b,))]
    # (Not format(): a name may have braces)
    return [(line.replace("{files}", replica_ops.files_text(len(items))),
             ["%s -> %s" % item if isinstance(item, tuple) else item for item in items])
            for items, line in things if items]
