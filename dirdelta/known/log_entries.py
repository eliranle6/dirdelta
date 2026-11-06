"""What a sync or a sort changed in each replica, and the entries offered for their logs once it's done"""
import collections
import datetime

from googleapiclient.errors import HttpError

from dirdelta.known import replicalog
from dirdelta.known import replicas
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


class Changes(object):
    """What a sync or an inbox's sort changed in each replica (live, not in a dry run), by its path,
    for an entry of its log: how many files were copied into it (from where), removed from it, moved
    in it, or moved out of it (to where)"""
    def __init__(self):
        # {path: {(verb, 'from' or 'to', where, or None): how many files}}, in the order they came
        self._counts = collections.OrderedDict()
        # {path: when it was last changed (a datetime)}
        self._when = {}

    def note(self, path, verb, count, place=None, preposition='from'):
        """Note that count files were copied (verb 'copied', from place), 'removed' or 'moved' (to
        place, with preposition 'to') in the replica at path"""
        if count:
            counts = self._counts.setdefault(path, collections.OrderedDict())
            key = (verb, preposition if place else None, place)
            counts[key] = counts.get(key, 0) + count
            self._when[path] = datetime.datetime.now()

    def when(self, path):
        """When the replica at path was last changed (a datetime), or None if it wasn't"""
        return self._when.get(path)

    def paths(self):
        """The paths of the replicas changed, in the order they were"""
        return list(self._counts)

    def summary(self, path):
        """What changed in the replica at path, as an entry's text, e.g. 'copied 12 files from
        cloud/eliran; removed 3 files' ('' if nothing)"""
        return '; '.join("%s %s%s" % (verb, "1 file" if count == 1 else "%d files" % (count,),
                                      " %s %s" % (preposition, place) if place else "")
                         for (verb, preposition, place), count in self._counts.get(path, {}).items())

def note_seen(replicas_and_paths, known_replicas):
    """Note in known_replicas (a replicas.Replicas; not saved) that the replicas of replicas_and_paths
    ([(tree, path)]) are being synced or sorted now, with their logs' last entries"""
    now = datetime.datetime.now()
    for tree, path in replicas_and_paths:
        text = replicalog.read(tree)
        known_replicas.note_seen(replicalog.identity(path), path, replicalog.last_entry(text) if text else None, now)


# The choices for adding an entry to a changed replica's log (what each does first, the path last,
# so a long one doesn't hide it)
NO_ENTRY = "No"
ADD_ENTRY = "Add it to its %s (%s)"
EDIT_ENTRY = "Edit it first"


def offer_entries(changes, replicas_and_paths, known_replicas):
    """After a sync or an inbox's sort, for each replica it changed (changes, a Changes: what was
    copied into it, removed from it, moved in it), offer to add an entry saying so to its log
    (only its: the other replica's log is of the other's changes), today's: e.g. '30.10.2026 -
    copied 12 files from cloud/eliran'. replicas_and_paths: [(the replica's tree, whose
    displayname() changes has it by, its path)]. Notes in known_replicas (a replicas.Replicas,
    saved) when each was changed, and its log's last entry."""
    today = datetime.date.today()
    by_name = {tree.displayname(): (tree, path) for tree, path in replicas_and_paths}
    for name in changes.paths():
        tree, path = by_name[name]
        text = changes.summary(name)
        known_replicas.note_changed(replicalog.identity(path), changes.when(name) or datetime.datetime.now())
        while True:
            line = replicalog.entry_line(today, text)
            add = picker.Option(ADD_ENTRY, ADD_ENTRY % (replicalog.LOG_NAME, path))
            header = "Add to %s? (%s)\n\n  %s" % (replicalog.LOG_NAME, path, line)
            answer = picker.pick_option([NO_ENTRY, add, EDIT_ENTRY], header=header, title="Log entry")
            if answer == EDIT_ENTRY:
                edited = messages.ask("The entry of %s's %s" % (path, replicalog.LOG_NAME),
                                      ["What changed in %s (after its date, %s):" % (
                                          path, today.strftime(replicalog.DATE_FORMAT))],
                                      "> ", text, dryrun.label())
                text = edited or text
                continue
            if answer == ADD_ENTRY:
                _add_entry(tree, path, line, replicalog.Entry(today, text), known_replicas)
            break
    if changes.paths():
        replicas.save(known_replicas)


def _add_entry(tree, path, line, entry, known_replicas):
    """Add line (an entry) to the log of the replica at path (tree), made if it has none"""
    try:
        replicalog.write(tree, replicalog.with_entry(replicalog.read(tree) or '', line))
    except (OSError, HttpError) as error:
        messages.show("Cannot add the entry to %s's %s" % (path, replicalog.LOG_NAME), [str(error)], dryrun.label(), 'red')
        return
    known_replicas.note_entry(replicalog.identity(path), entry)
