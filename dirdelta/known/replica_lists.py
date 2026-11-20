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
        """The pairs of the user's replicas to sync: with a main replica, it with each of the others (it first),
        then the pairs the user added; else every two of them, (a, b) the way a sync last had them if one did"""
        replicas = self.replica_paths()
        if self.main_replica in replicas:
            found = [(self.main_replica, other) for other in replicas if other != self.main_replica]
            for pair in self.extra_pairs:
                if all(path in replicas for path in pair) and frozenset(pair) not in {frozenset(one) for one in found}:
                    found.append(tuple(pair))
            return found
        used = {frozenset(pair): pair for pair in self.favorites + self.history}
        return [used.get(frozenset(pair), pair) for pair in itertools.combinations(replicas, 2)]

    def set_main(self, path):
        """Make the replica at path the main one (None: none, every two a pair)"""
        self.main_replica = paths.normalized(path) if path else None

    def add_pair(self, path_a, path_b):
        """Add a pair to sync besides the main replica's (two of the user's replicas, neither the main one's pair)"""
        pair = (paths.normalized(path_a), paths.normalized(path_b))
        if pair[0] != pair[1] and frozenset(pair) not in {frozenset(one) for one in self.extra_pairs}:
            self.extra_pairs.append(pair)

    def remove_pair(self, path_a, path_b):
        gone = frozenset((paths.normalized(path_a), paths.normalized(path_b)))
        self.extra_pairs = [pair for pair in self.extra_pairs if frozenset(pair) != gone]

    def is_extra_pair(self, path_a, path_b):
        """Whether the pair is one the user added (not one of the main replica's)"""
        return frozenset((paths.normalized(path_a), paths.normalized(path_b))) in {frozenset(one) for one in self.extra_pairs}

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
