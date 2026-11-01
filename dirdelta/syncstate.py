"""Whether a pair of replicas is in sync, as far as dirdelta knows: what a sync of them last found
(replicas.Replicas.comparison(): how many of each one's files the other lacked), and whether either
was changed since (by dirdelta: another sync, an inbox's sort; or its log has a later entry). From
that: in sync, one ahead of the other (it has files the other lacks, and not the other way around),
branched (each has files the other lacks), or not known. No screen here: what a state is shown as
(its mark, its color, its words) is for the menus to use as they will."""
import collections

IN_SYNC = 'in sync'
# A has files B lacks, and B none that A lacks (B is behind); and the other way around
A_AHEAD = 'a ahead'
B_AHEAD = 'b ahead'
BRANCHED = 'branched'
UNKNOWN = 'unknown'

# kind: one of the above. only_a, only_b: how many of a's files b lacked, and of b's a lacked (None
# if not known). when: when they were compared ('YYYY-MM-DD HH:MM', or None). changed: the paths of
# the ones changed since (so it may not be so anymore)
State = collections.namedtuple('State', ['kind', 'only_a', 'only_b', 'when', 'changed'])

# The marks of the states (before a pair in the menus), and their colors; a state with a replica
# changed since is shown in CHANGED_COLOR, whatever it was
MARKS = {IN_SYNC: '≡', A_AHEAD: '»', B_AHEAD: '«', BRANCHED: '≠', UNKNOWN: '?'}
COLORS = {IN_SYNC: 'green', A_AHEAD: 'yellow', B_AHEAD: 'yellow', BRANCHED: 'red', UNKNOWN: 'grey'}
CHANGED_COLOR = 'grey'


def of(known, path_a, path_b):
    """The State of the pair, by known (a replicas.Replicas)"""
    comparison = known.comparison(path_a, path_b) if known is not None else None
    if comparison is None:
        return State(UNKNOWN, None, None, None, [])
    only_a, only_b = comparison['only']
    return State(found(only_a, only_b), only_a, only_b, comparison['when'],
                 [path for path in (path_a, path_b) if _changed_since(known, path, comparison['when'])])


def found(only_a, only_b):
    """The kind of state of a pair where a has only_a files b lacks, and b only_b that a lacks"""
    if not only_a and not only_b:
        return IN_SYNC
    if only_a and only_b:
        return BRANCHED
    return A_AHEAD if only_a else B_AHEAD


def mark(state):
    """(The state's mark, its color)"""
    return MARKS[state.kind], CHANGED_COLOR if state.changed else COLORS[state.kind]


def describe(state, path_a, path_b):
    """What the state is, in words, e.g. 'In sync (as of 01.11.2026 14:05)'"""
    def files(count):
        return "1 file" if count == 1 else "%d files" % (count,)
    if state.kind == UNKNOWN:
        return "Not compared yet: sync them to know"
    text = {IN_SYNC: "In sync: each has all the other's files",
            A_AHEAD: "%s is ahead: it has %s that %s lacks, and lacks none of its" % (
                path_a, files(state.only_a), path_b),
            B_AHEAD: "%s is ahead: it has %s that %s lacks, and lacks none of its" % (
                path_b, files(state.only_b), path_a),
            BRANCHED: "Branched: %s has %s that %s lacks, and %s has %s that %s lacks" % (
                path_a, files(state.only_a), path_b, path_b, files(state.only_b), path_a)}[state.kind]
    if state.when:
        text += " (as of %s)" % (_shown_time(state.when),)
    if state.changed:
        text += "; changed since: %s" % (", ".join(state.changed),)
    return text


def help_lines():
    """The marks' legend, for a menu's ? help"""
    return ["%s %s" % (MARKS[kind], words) for kind, words in (
        (IN_SYNC, "in sync (green): when last synced, each had all the other's files"),
        (A_AHEAD, "or %s one ahead (yellow): the replica it points from has files the other lacks, "
                  "and lacks none of the other's" % (MARKS[B_AHEAD],)),
        (BRANCHED, "branched (red): each has files the other lacks"),
        (UNKNOWN, "not known (grey): never compared"))] + [
        "A mark in grey: a replica was changed since (by another sync or a sort, or its log has a later "
        "entry), so it may not be so anymore"]


def _changed_since(known, path, when):
    """Whether the replica at path was changed after when, as far as known says: by dirdelta, or by
    its log's last entry (a date: a later day's)"""
    info = known.info_at(path) or {}
    if (info.get('changed') or '') > when:
        return True
    entry_date = (info.get('last_entry') or {}).get('date') or ''
    return entry_date > when[:10]


def _shown_time(when):
    """'YYYY-MM-DD HH:MM' as 'DD.MM.YYYY HH:MM'"""
    date, _, hours = when.partition(' ')
    year, month, day = date.split('-')
    return ('%s.%s.%s %s' % (day, month, year, hours)).strip()
