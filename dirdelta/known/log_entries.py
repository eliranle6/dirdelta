"""What a sync or a sort changed in each replica, and the entries offered for their logs once it's done"""
import collections
import datetime


from dirdelta.known import replicalog
from dirdelta.known import replicas


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


def offer_entries(changes, replicas_and_paths, known_replicas):
    """After a sync or an inbox's sort, note in known_replicas (a replicas.Replicas, saved) when each replica it changed
    (changes, a Changes) was changed. No entry is offered for its last_update.txt any more (since 2026-11-21): what a sync
    changed is in the replica's own history (synchistory.py). replicas_and_paths: [(the replica's tree, whose
    displayname() changes has it by, its path)]."""
    by_name = {tree.displayname(): (tree, path) for tree, path in replicas_and_paths}
    for name in changes.paths():
        _, path = by_name[name]
        known_replicas.note_changed(replicalog.identity(path), changes.when(name) or datetime.datetime.now())
    if changes.paths():
        replicas.save(known_replicas)
