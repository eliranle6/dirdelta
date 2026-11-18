"""A user's replicas, inboxes and pairs (known/replica_lists.py)"""
import unittest

from dirdelta.known.replica_history import Replicas


class ReplicaListsTest(unittest.TestCase):
    def test_the_replicas_are_the_ones_added_synced_or_sorted_into_and_the_inboxes_apart(self):
        known = Replicas(history=[('/disk/me', 'cloud/me')], sorts=[('cloud/unsorted', '/disk/me')])
        known.add_replica('/other/me')
        known.add_inbox('/home/me/Downloads/')
        self.assertEqual(['/other/me', '/disk/me', 'cloud/me'], known.replica_paths())
        self.assertEqual(['/home/me/Downloads', 'cloud/unsorted'], known.inbox_paths())

    def test_every_two_replicas_are_a_pair_the_way_around_a_sync_had_them(self):
        known = Replicas(history=[('cloud/me', '/disk/me')])
        known.add_replica('/other/me')
        self.assertEqual({('cloud/me', '/disk/me'), ('/other/me', 'cloud/me'), ('/other/me', '/disk/me')}, set(known.pairs()))

    def test_a_forgotten_replica_is_in_no_pair_or_sort_any_more_and_the_others_stay(self):
        known = Replicas(history=[('/disk/me', 'cloud/me')], favorites=[('/disk/me', 'cloud/me')],
                         sorts=[('cloud/unsorted', '/disk/me')])
        known.forget('/disk/me')
        self.assertEqual((['cloud/me'], ['cloud/unsorted'], []), (known.replica_paths(), known.inbox_paths(), known.sorts))

    def test_an_inbox_added_isnt_a_replica_any_more(self):
        known = Replicas()
        known.add_replica('/disk/in')
        known.add_inbox('/disk/in')
        self.assertEqual(([], ['/disk/in']), (known.replica_paths(), known.inbox_paths()))


if __name__ == '__main__':
    unittest.main()
