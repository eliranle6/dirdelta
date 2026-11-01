import datetime
import unittest

from dirdelta import replicalog
from dirdelta import replicas
from dirdelta import syncstate


class SyncStateTest(unittest.TestCase):
    def setUp(self):
        self.known = replicas.Replicas()
        self.when = datetime.datetime(2026, 11, 1, 14, 5)
        for identity, path in (('id:a', '/a'), ('id:b', 'cloud/b')):
            self.known.note_seen(identity, path, None, self.when)

    def state(self, only_a, only_b):
        self.known.note_compared('/a', 'cloud/b', only_a, only_b, self.when)
        return syncstate.of(self.known, '/a', 'cloud/b')

    def test_kinds_by_what_each_lacked(self):
        self.assertEqual(self.state(0, 0).kind, syncstate.IN_SYNC)
        self.assertEqual(self.state(3, 0).kind, syncstate.A_AHEAD)
        self.assertEqual(self.state(0, 2).kind, syncstate.B_AHEAD)
        self.assertEqual(self.state(3, 2).kind, syncstate.BRANCHED)
        self.assertEqual(syncstate.of(self.known, '/a', '/c').kind, syncstate.UNKNOWN)

    def test_either_way_around(self):
        self.state(3, 0)
        self.assertEqual(syncstate.of(self.known, 'cloud/b', '/a').kind, syncstate.B_AHEAD)

    def test_a_replica_changed_since_greys_the_mark(self):
        state = self.state(0, 0)
        self.assertEqual(syncstate.mark(state), ('≡', 'green'))
        self.known.note_changed('id:b', datetime.datetime(2026, 11, 1, 16, 0))
        state = syncstate.of(self.known, '/a', 'cloud/b')
        self.assertEqual(state.changed, ['cloud/b'])
        self.assertEqual(syncstate.mark(state), ('≡', 'grey'))
        self.assertIn("changed since: cloud/b", syncstate.describe(state, '/a', 'cloud/b'))

    def test_a_later_log_entry_is_a_change(self):
        self.state(0, 0)
        self.known.note_entry('id:a', replicalog.Entry(datetime.date(2026, 11, 2), 'added things'))
        self.assertEqual(syncstate.of(self.known, '/a', 'cloud/b').changed, ['/a'])

    def test_described(self):
        self.assertEqual(syncstate.describe(self.state(3, 0), '/a', 'cloud/b'),
                         "/a is ahead: it has 3 files that cloud/b lacks, and lacks none of its (as of 01.11.2026 14:05)")
        self.assertTrue(syncstate.describe(self.state(1, 2), '/a', 'cloud/b').startswith(
            "Branched: /a has 1 file that cloud/b lacks, and cloud/b has 2 files that /a lacks"))


if __name__ == '__main__':
    unittest.main()
