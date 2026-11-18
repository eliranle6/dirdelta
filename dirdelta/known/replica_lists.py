"""A user's replicas and inboxes (ReplicaLists, a mixin of Replicas): the replicas, copies of their one
tree, any two of them a pair to sync (pairs()); and the inboxes, where new files come (a phone's photos, a
Drive folder), each sorted into that tree. Each is one added (added_replicas, added_inboxes) or one a sync
or a sort used (the history's, the favorites' and the sorts' paths, as before 2026-11-18), unless it was
forgotten."""
import itertools

from dirdelta.trees import paths


class ReplicaLists(object):
    def replica_paths(self):
        """The user's replicas: the ones added, then the ones synced or sorted into"""
        inboxes = set(self.inbox_paths())
        found = self.added_replicas + [path for pair in self.favorites + self.history for path in pair] + \
            [root for _, root in self.sorts]
        return [path for path in dict.fromkeys(found) if path not in inboxes]

    def inbox_paths(self):
        """The user's inboxes: the ones added, then the ones sorted"""
        return list(dict.fromkeys(self.added_inboxes + [inbox for inbox, _ in self.sorts]))

    def pairs(self):
        """Every two of the user's replicas, (a, b) the way a sync last had them if one did"""
        used = {frozenset(pair): pair for pair in self.favorites + self.history}
        return [used.get(frozenset(pair), pair) for pair in itertools.combinations(self.replica_paths(), 2)]

    def add_replica(self, path):
        path = paths.normalized(path)
        self.added_inboxes = [old for old in self.added_inboxes if old != path]
        if path not in self.added_replicas:
            self.added_replicas.append(path)

    def add_inbox(self, path):
        path = paths.normalized(path)
        self.added_replicas = [old for old in self.added_replicas if old != path]
        if path not in self.added_inboxes:
            self.added_inboxes.append(path)

    def forget(self, path):
        """Not the user's replica or inbox any more: nor in a pair or a sort (nothing in it is touched);
        the others stay theirs"""
        replicas, inboxes = self.replica_paths(), self.inbox_paths()
        self.added_replicas = [kept for kept in replicas if kept != path]
        self.added_inboxes = [kept for kept in inboxes if kept != path]
        self.added_replicas = [old for old in self.added_replicas if old != path]
        self.added_inboxes = [old for old in self.added_inboxes if old != path]
        self.history = [pair for pair in self.history if path not in pair]
        self.favorites = [pair for pair in self.favorites if path not in pair]
        self.sorts = [pair for pair in self.sorts if path not in pair]
