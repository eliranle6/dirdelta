"""An import's overview (phoneimport/overview.py): what each replica has of its files, and how sure"""
import unittest

from dirdelta.phoneimport import known, overview, store


def info(state=store.COPIED, sha1='s', target=None):
    return {'size': 1, 'mtime': 0, 'state': state, 'sha1': sha1, 'target': target}


class OverviewTest(unittest.TestCase):
    FILES = {'a.jpg': info(), 'b.jpg': info(state=store.PENDING, sha1=None, target='Trip'), 'c.jpg': info(target='Trip'),
             'd.jpg': info(state=store.MOVED)}
    HAVES = {'a.jpg': [('/win', 'x/a.jpg', known.SAME_CONTENTS), ('cloud/me', 'a.jpg', known.SAME_NAME_AND_SIZE)],
             'b.jpg': [('/win', 'b.jpg', known.SAME_NAME_AND_SIZE)], 'c.jpg': [], 'd.jpg': []}

    def test_each_replica_has_what_by_contents_or_by_name_only_and_why(self):
        found = overview.of(self.FILES, self.HAVES, ['/win', 'cloud/me'])
        win, cloud = found['replicas']
        self.assertEqual((2, 1, 1, 0, 2), (win['have'], win['contents'], win['namePhoneUnhashed'],
                                           win['nameReplicaUnhashed'], win['missing']))
        self.assertEqual((1, 0, 1, 3), (cloud['have'], cloud['contents'], cloud['nameReplicaUnhashed'], cloud['missing']))
        self.assertEqual((2, 1), (found['inNone'], found['inAll']))

    def test_how_many_are_hashed_chosen_and_ready_to_move(self):
        found = overview.of(self.FILES, self.HAVES, ['/win'])
        self.assertEqual((4, 3), (found['total'], found['hashed']))
        self.assertEqual((2, 1), (found['chosen'], found['ready']))
        self.assertEqual(1, found['counts'][store.MOVED])

    def test_while_the_replicas_are_checked_theres_no_count_of_them(self):
        found = overview.of(self.FILES, None, ['/win'])
        self.assertFalse(found['checked'])
        self.assertIsNone(found['inNone'])
        self.assertEqual(0, found['replicas'][0]['have'])


if __name__ == '__main__':
    unittest.main()
