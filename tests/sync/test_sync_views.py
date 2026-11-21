"""The sync's views of its differences (sync/view.py): the view asked for with the switch, and both sides' files acted on
at once (bothsides.py)"""
import os
import unittest
from unittest import mock

from dirdelta.matching import differing
from dirdelta.sync import bothsides
from dirdelta.sync import view
from dirdelta.sync.combined import confirming
from dirdelta.ui import frontend
from dirdelta.ui import picker
from combined_support import ReplicasTest

CHANGE = differing.Change(1, 2, None, None, differing.BY_SIZE)


class RequestedTest(unittest.TestCase):
    def test_the_pages_view_is_taken_once_else_the_other_mode(self):
        session = mock.Mock(view_request={'scope': view.ONLY_B, 'mode': view.ACT})
        with mock.patch.object(frontend, 'current', session):
            self.assertEqual((view.ONLY_B, view.ACT), view.requested(view.ALL, view.PLAN))
            # (Taken: the next switch without one is the terminal's, the other mode)
            self.assertEqual((view.ALL, view.ACT), view.requested(view.ALL, view.PLAN))
        self.assertEqual((view.DIFFER, view.PLAN), view.requested(view.DIFFER, view.ACT))


class BothSidesTest(ReplicasTest):
    def run_it(self, picks, answers, moved=None, only_moved=False):
        act = bothsides.BothSides(self.replica_a, self.replica_b, self.path_a, self.path_b, ['new/a.txt', 'gone.txt'],
                                  ['b.txt', 'old/b2.txt'], differing.Changes({'both.txt': CHANGE}), moved or {}, only_moved=only_moved)
        with mock.patch('dirdelta.ui.picker.pick_files', side_effect=picks) as self.pick_files, \
                mock.patch('dirdelta.ui.picker.pick_option', side_effect=answers) as self.pick_option, \
                mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            changed = act.run()
        return act, changed

    def test_checked_files_of_both_sides_are_each_copied_to_where_its_missing(self):
        _, changed = self.run_it([picker.Picked('', 'b.txt', ['new/a.txt', 'b.txt', 'both.txt'])],
                                 [bothsides.COPY, confirming.CONFIRM_YES])
        self.assertTrue(changed)
        self.assertTrue(os.path.exists(os.path.join(self.path_b, 'new/a.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.path_a, 'b.txt')))
        # (The one that differs is left: which version wins is Plan's)
        self.assertNotEqual(self.read(self.path_a, 'both.txt'), self.read(self.path_b, 'both.txt'))
        self.assertIn("1 that differ", self.pick_option.call_args_list[0].kwargs['header'])

    def test_removing_asks_twice_and_removes_each_from_where_it_is(self):
        _, changed = self.run_it([picker.Picked('', 'b.txt', ['gone.txt', 'b.txt'])],
                                 [bothsides.REMOVE, confirming.CONFIRM_YES, confirming.CONFIRM_SURE])
        self.assertTrue(changed)
        self.assertFalse(os.path.exists(os.path.join(self.path_a, 'gone.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.path_b, 'b.txt')))

    def test_moved_ones_alone_are_moved_to_match(self):
        _, changed = self.run_it([picker.Picked('', 'gone.txt', ['gone.txt'])], [bothsides.MOVE_IN_A, confirming.CONFIRM_YES],
                                 moved={'gone.txt': 'old/b2.txt'}, only_moved=True)
        self.assertTrue(changed)
        self.assertEqual(['gone.txt'], self.pick_files.call_args.args[1])
        self.assertTrue(os.path.exists(os.path.join(self.path_a, 'old/b2.txt')))

    def test_the_switch_ends_it_asking_for_the_pages_view(self):
        session = mock.Mock(view_request={'scope': view.ALL, 'mode': view.PLAN})
        with mock.patch.object(frontend, 'current', session):
            act, changed = self.run_it([picker.Picked(view.SWITCH_KEY, '', [])], [])
        self.assertFalse(changed)
        self.assertEqual((view.ALL, view.PLAN), act.switch)


if __name__ == '__main__':
    unittest.main()
