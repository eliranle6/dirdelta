"""The combined tree of a sync: its entries, the plan the user's states make, confirming it, and
doing it"""
import os
import unittest
from unittest import mock

from dirdelta.claude import aiplan
from dirdelta.known import log_entries
from dirdelta.matching import differing
from dirdelta.matching import elsewhere
from dirdelta.sync.combined import doing
from dirdelta.sync.combined import moved
from dirdelta.sync.combined import plan as plans
from dirdelta.sync.combined import screen
from dirdelta.trees import dirtree
from dirdelta.ui import picker
from combined_support import ReplicasTest

CHANGE = differing.Change(1, 2, None, None, differing.BY_SIZE)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.grouped = plans.groups(['a1', 'd/a2'], ['b1'], differing.Changes({'c': CHANGE}))

    def test_each_file_is_in_its_group(self):
        self.assertEqual(self.grouped, {'a1': plans.ONLY_A, 'd/a2': plans.ONLY_A, 'b1': plans.ONLY_B, 'c': plans.DIFFER})

    def test_each_arrow_does_what_it_says_for_each_group(self):
        chosen = {'a1': plans.TO_B, 'd/a2': plans.TO_A, 'b1': plans.TO_B, 'c': plans.TO_A}
        self.assertEqual(plans.plan_of(chosen, self.grouped),
                         plans.Plan(copy_to_b=['a1'], copy_to_a=[], replace_b=[], replace_a=['c'],
                                    remove_from_a=['d/a2'], remove_from_b=['b1'], move_in_b=[], move_in_a=[]))
        chosen = {'b1': plans.TO_A, 'c': plans.TO_B, 'a1': plans.SKIP}
        plan = plans.plan_of(chosen, self.grouped)
        self.assertEqual((plan.copy_to_a, plan.replace_b, plans.removals(plan)), (['b1'], ['c'], 0))
        self.assertTrue(plans.is_empty(plans.plan_of({'a1': plans.SKIP}, self.grouped)))

    def test_the_summary_says_each_thing_done(self):
        plan = plans.plan_of({'a1': plans.TO_B, 'd/a2': plans.TO_B, 'b1': plans.TO_B, 'c': plans.TO_A}, self.grouped)
        self.assertEqual(plans.summary(plan, 'A', 'B'), [("Copy 2 files from A to B", ['a1', 'd/a2']),
                                                         ("Replace A's versions of 1 file with B's", ['c']),
                                                         ("Remove 1 file from B", ['b1'])])

    def test_a_moved_pair_is_one_entry_at_as_path_moved_either_way(self):
        moved = {'d/a2': 'b1'}
        grouped = plans.groups(['a1', 'd/a2'], ['b1', 'b2'], differing.Changes(), moved)
        self.assertEqual(grouped, {'a1': plans.ONLY_A, 'd/a2': plans.MOVED, 'b2': plans.ONLY_B})
        plan = plans.plan_of({'d/a2': plans.TO_B}, grouped, moved)
        self.assertEqual((plan.move_in_b, plan.move_in_a), ([('b1', 'd/a2')], []))
        plan = plans.plan_of({'d/a2': plans.TO_A}, grouped, moved)
        self.assertEqual(plan.move_in_a, [('d/a2', 'b1')])
        self.assertEqual(plans.summary(plan, 'A', 'B'), [("Move 1 file in A to where B has them", ['d/a2 -> b1'])])

    def test_entries_keep_each_dirs_files_together_and_the_states_chosen(self):
        entries = plans.entries(self.grouped, plans.allowed(dirtree.DirTree('/a'), dirtree.DirTree('/b')), {'b1': plans.TO_A})
        self.assertEqual([entry.relpath for entry in entries], ['a1', 'b1', 'c', 'd/a2'])
        self.assertEqual(entries[1].state, plans.TO_A)
        self.assertEqual(entries[0].state, '')


class AllowedTest(ReplicasTest):
    def test_an_arrow_is_allowed_only_where_it_can_be_done(self):
        local, cloud = self.replica_a, dirtree.DirTree('cloud/b')
        both = (plans.SKIP, plans.TO_B, plans.TO_A)
        self.assertEqual(plans.allowed(local, cloud), {plans.ONLY_A: both, plans.ONLY_B: both, plans.DIFFER: both,
                                                       plans.MOVED: both})
        # A read-only replica can't be changed: no copying into it, removing from it nor moving in it
        with mock.patch('os.access', return_value=False):
            self.assertEqual(plans.allowed(local, cloud), {plans.ONLY_A: (plans.SKIP, plans.TO_B),
                                                           plans.ONLY_B: (plans.SKIP, plans.TO_B),
                                                           plans.DIFFER: (plans.SKIP, plans.TO_B),
                                                           plans.MOVED: (plans.SKIP, plans.TO_B)})
        # Nor are files copied within Drive (removing and moving are)
        other_cloud = dirtree.DirTree('cloud/c')
        self.assertEqual(plans.allowed(cloud, other_cloud), {plans.ONLY_A: (plans.SKIP, plans.TO_A),
                                                             plans.ONLY_B: (plans.SKIP, plans.TO_B),
                                                             plans.DIFFER: (plans.SKIP,), plans.MOVED: both})


class MovedTest(ReplicasTest):
    def find(self, checked):
        return moved.find(['new/a.txt', 'gone.txt'], ['b.txt', 'old/b2.txt'], self.replica_a, elsewhere.Index(self.replica_a),
                          elsewhere.Index(self.replica_b), checked)

    def test_a_pair_is_only_where_the_contents_are_known_the_same(self):
        self.assertEqual(self.find({}), {})
        self.assertEqual(self.find({'gone.txt': {'old/b2.txt': True}}), {'gone.txt': 'old/b2.txt'})
        self.assertEqual(self.find({'gone.txt': {'old/b2.txt': False}}), {})

    def test_by_the_hashes_known(self):
        # Hashed on both sides (as a hashing job would): the same, whatever their names
        for root, relpath in ((self.path_a, 'gone.txt'), (self.path_b, 'old/b2.txt')):
            with open(os.path.join(root, relpath), 'w') as f:
                f.write('the same')
        hashes = {os.path.join(self.path_a, 'gone.txt'): 'h', os.path.join(self.path_b, 'old/b2.txt'): 'h'}
        with mock.patch('dirdelta.matching.elsewhere.index.Index.known',
                        lambda index, relpath: {'sha1': hashes[index.replica.local_path(relpath)]}
                        if index.replica.local_path(relpath) in hashes else {}), \
                mock.patch('dirdelta.matching.elsewhere.index.Index.files_hashed',
                           lambda index, algorithm, value: [relpath for relpath in ('old/b2.txt',)
                                                            if index.replica is self.replica_b and value == 'h']):
            self.assertEqual(self.find({}), {'gone.txt': 'old/b2.txt'})

    def test_duplicates_arent_paired(self):
        checked = {'gone.txt': {'old/b2.txt': True}, 'new/a.txt': {'old/b2.txt': True}}
        self.assertEqual(self.find(checked), {})


class DoingTest(ReplicasTest):
    def test_moves_go_first(self):
        plan = plans.Plan(copy_to_b=[], copy_to_a=[], replace_b=[], replace_a=[], remove_from_a=[], remove_from_b=[],
                          move_in_b=[('old/b2.txt', 'gone.txt')])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            doing.do(plan, self.replica_a, self.replica_b)
        self.assertEqual(self.read(self.path_b, 'gone.txt'), 'old/b2.txt')
        self.assertFalse(os.path.exists(os.path.join(self.path_b, 'old/b2.txt')))

    def test_copies_replaces_and_removes_each_way(self):
        plan = plans.Plan(copy_to_b=['new/a.txt'], copy_to_a=['b.txt'], replace_b=[], replace_a=['both.txt'],
                          remove_from_a=['gone.txt'], remove_from_b=['old/b2.txt'])
        changes = log_entries.Changes()
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            doing.do(plan, self.replica_a, self.replica_b, changes)
        self.assertEqual(self.read(self.path_b, 'new/a.txt'), 'new/a.txt')
        self.assertEqual(self.read(self.path_a, 'b.txt'), 'b.txt')
        self.assertEqual(self.read(self.path_a, 'both.txt'), "B's longer version")
        self.assertFalse(os.path.exists(os.path.join(self.path_a, 'gone.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.path_b, 'old/b2.txt')))
        # Removed and replaced files go to the trash (a dir all of whose files are removed: as one)
        self.assertEqual(sorted(os.listdir(self.trash)), ['both.txt', 'gone.txt', 'old'])
        self.assertEqual(changes.summary(self.path_b), "copied 1 file from %s; removed 1 file" % (self.path_a,))

    def test_a_dry_run_changes_nothing(self):
        plan = plans.Plan(copy_to_b=['new/a.txt'], copy_to_a=[], replace_b=['both.txt'], replace_a=[],
                          remove_from_a=['gone.txt'], remove_from_b=[])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            doing.do(plan, self.replica_a, self.replica_b)
        self.assertFalse(os.path.exists(os.path.join(self.path_b, 'new')))
        self.assertTrue(os.path.exists(os.path.join(self.path_a, 'gone.txt')))
        self.assertEqual(self.read(self.path_b, 'both.txt'), "B's longer version")

    def test_once_stopped_the_rest_isnt_done(self):
        plan = plans.Plan(copy_to_b=['new/a.txt'], copy_to_a=[], replace_b=[], replace_a=[],
                          remove_from_a=['gone.txt'], remove_from_b=[])
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=KeyboardInterrupt):
            doing.do(plan, self.replica_a, self.replica_b)
        self.assertTrue(os.path.exists(os.path.join(self.path_a, 'gone.txt')))


class ScreenTest(ReplicasTest):
    def run_screen(self, picks, answers, changes=None):
        """Run the screen with the pickers' answers: picks, pick_states()'s (each a StatesPicked, or
        None), answers, pick_option()'s; returns what it returned"""
        changes = changes if changes is not None else differing.Changes({'both.txt': CHANGE})
        sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b,
                                   ['gone.txt', 'new/a.txt'], ['b.txt', 'old/b2.txt'], changes)
        self.pick_states = mock.Mock(side_effect=picks)
        with mock.patch('dirdelta.ui.picker.pick_states', self.pick_states), \
                mock.patch('dirdelta.ui.picker.pick_option', side_effect=answers), \
                mock.patch('dirdelta.sync.combined.doing.do') as self.do:
            return sync.run()

    def test_the_plan_is_done_once_confirmed(self):
        chosen = {'new/a.txt': plans.TO_B, 'both.txt': plans.TO_A}
        self.assertTrue(self.run_screen([picker.StatesPicked('new', chosen)], [screen.CONFIRM_YES]))
        plan = self.do.call_args.args[0]
        self.assertEqual((plan.copy_to_b, plan.replace_a), (['new/a.txt'], ['both.txt']))

    def test_no_goes_back_to_the_tree_as_it_was(self):
        chosen = {'new/a.txt': plans.TO_B}
        self.assertFalse(self.run_screen([picker.StatesPicked('new', chosen), None], [screen.CONFIRM_NO]))
        self.do.assert_not_called()
        again = self.pick_states.call_args_list[1]
        self.assertEqual(again.kwargs['selected'], 'new')
        self.assertEqual({entry.relpath: entry.state for entry in again.args[1]}['new/a.txt'], plans.TO_B)

    def test_removing_asks_twice(self):
        chosen = {'gone.txt': plans.TO_A}
        self.assertFalse(self.run_screen([picker.StatesPicked('', chosen), None], [screen.CONFIRM_YES, screen.CONFIRM_NO]))
        self.do.assert_not_called()
        self.assertTrue(self.run_screen([picker.StatesPicked('', chosen)], [screen.CONFIRM_YES, screen.CONFIRM_SURE]))
        self.assertEqual(self.do.call_args.args[0].remove_from_a, ['gone.txt'])

    def test_tabs_are_for_the_groups_that_have_files(self):
        self.run_screen([None], [], changes=differing.Changes())
        self.assertEqual([tab.title for tab in self.pick_states.call_args.kwargs['tabs']], ['All', 'Only in LocalDisk:A', 'Only in LocalDisk:B'])

    def test_a_moved_pair_has_its_tab_and_says_where_b_has_it(self):
        sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b, ['gone.txt'], ['old/b2.txt'],
                                   differing.Changes(), moved={'gone.txt': 'old/b2.txt'})
        pick_states = mock.Mock(return_value=None)
        with mock.patch('dirdelta.ui.picker.pick_states', pick_states):
            sync.run()
        self.assertEqual([tab.title for tab in pick_states.call_args.kwargs['tabs']], ['All', 'Moved'])
        self.assertEqual([entry.relpath for entry in pick_states.call_args.args[1]], ['gone.txt'])
        self.assertEqual(picker.unstyled(pick_states.call_args.kwargs['shown_as']()['gone.txt']),
                         "gone.txt  moved: in LocalDisk:B at old/b2.txt")

    def test_a_moved_files_preview_says_how_its_path_changed_word_by_word(self):
        sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b, ['photos/2024/a.jpg'],
                                   ['photos/a.jpg'], differing.Changes(), moved={'photos/2024/a.jpg': 'photos/a.jpg'})
        lines = [picker.unstyled(line) for line in sync._file_preview('photos/2024/a.jpg')]
        self.assertIn("From LocalDisk:B's path to LocalDisk:A's: photos/{+2024/+}a.jpg", lines)
        self.assertEqual(moved.path_diff('old/moved.txt', 'docs/moved.txt'),
                         [('[-old/-]', 'red'), ('{+docs/+}', 'green'), ('moved.txt', None)])

    def test_the_ais_steps_set_the_arrows_to_review_in_the_tree(self):
        steps = [aiplan.Step(plans.TO_B, 'new/a.txt', None, "it's new"), aiplan.Step(plans.TO_A, 'both.txt', None, "B's is newer")]
        with mock.patch('dirdelta.screens.aiplan_screen.ask', return_value=('sync the new ones', steps)) as ask:
            self.run_screen([picker.StatesPicked('new', {'b.txt': plans.TO_A}, 'a'), None], [])
        task = ask.call_args.args[0]
        self.assertFalse(ask.call_args.kwargs['review'])
        notes = {file.relpath: file.note for file in task.files}
        self.assertEqual(notes['b.txt'], 'only in LocalDisk:B')
        self.assertTrue(notes['both.txt'].startswith('in both, different: '))
        self.assertEqual(task.focus, ['new/a.txt'])
        again = self.pick_states.call_args_list[1]
        states = {entry.relpath: entry.state for entry in again.args[1]}
        # Its steps, and what was set before
        self.assertEqual((states['new/a.txt'], states['both.txt'], states['b.txt']), (plans.TO_B, plans.TO_A, plans.TO_A))
        self.assertIn("The AI set the arrows of 2 files", picker.unstyled(again.kwargs['footer']))

    def test_the_ai_cant_set_an_arrow_that_isnt_allowed(self):
        with mock.patch('dirdelta.sync.replica_ops.is_writable', side_effect=lambda replica: replica is not self.replica_a):
            sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b, ['gone.txt'], [],
                                       differing.Changes())
        task = sync._ai_task()
        checks = {action.name: action.check for action in task.actions}
        # A read-only: no removing from it
        self.assertIsNotNone(checks[plans.TO_A]('gone.txt', None))
        self.assertIsNone(checks[plans.TO_B]('gone.txt', None))

    def test_nothing_to_do_says_so(self):
        sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b, [], [], differing.Changes())
        with mock.patch('dirdelta.ui.picker.pick_states') as pick_states:
            self.assertFalse(sync.run())
        pick_states.assert_not_called()


if __name__ == '__main__':
    unittest.main()
