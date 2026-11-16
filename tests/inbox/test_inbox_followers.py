"""The sorted tree's other replicas: picked as a sort starts (none unless picked), and given copies of
what goes into the sorted tree"""
import os
from unittest import mock

import helpers
from dirdelta import inbox
from dirdelta.inbox import followers
from dirdelta.known import replicas
from dirdelta.ui import messages
from dirdelta.ui import picker
from inbox_support import InboxSortTest, Sort, YES


MOVE = 'Move it to a dir you pick'


class FollowersTest(InboxSortTest):
    def setUp(self):
        super().setUp()
        self.mirror = os.path.join(self.tmpdir, 'mirror')
        helpers.make_files(self.mirror, ['photos/old.jpg'])

    def move_a(self, **kwargs):
        self.sort([['a.txt'], None], [MOVE, YES], dirs=[os.path.join(self.root, 'docs')],
                  followers=[self.mirror], **kwargs)

    def printed(self):
        return '\n'.join(str(call.args[0]) for call in messages.print_line.call_args_list)

    def test_a_file_moved_into_the_sorted_tree_is_copied_into_a_picked_replica(self):
        self.move_a(is_dry_run=False)
        self.assertTrue(self.exists('sorted', 'docs', 'a.txt'))
        with open(os.path.join(self.mirror, 'docs', 'a.txt')) as f:
            self.assertEqual(f.read(), 'a.txt')
        self.assertIn('copied 1 file from %s' % (self.root,), self.sorter.changes.summary(self.mirror))

    def test_the_confirmation_says_where_they_go_too(self):
        self.move_a()
        confirmation = [call for call in self.pick_option.call_args_list if call.kwargs.get('title') == "Sure?"][0]
        self.assertIn(self.mirror, confirmation.kwargs['header'])

    def test_a_dry_run_copies_nothing_into_it(self):
        self.move_a(is_dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.mirror, 'docs')))

    def test_a_different_file_there_is_left_as_it_is_and_said(self):
        helpers.make_files(self.mirror, ['docs/a.txt'])
        with open(os.path.join(self.mirror, 'docs', 'a.txt'), 'w') as f:
            f.write('another version')
        self.move_a(is_dry_run=False)
        with open(os.path.join(self.mirror, 'docs', 'a.txt')) as f:
            self.assertEqual(f.read(), 'another version')
        self.assertIn('Left as they are', self.printed())

    def test_the_same_file_there_already_is_counted_not_copied(self):
        helpers.make_files(self.mirror, ['docs/a.txt'])
        with open(os.path.join(self.mirror, 'docs', 'a.txt'), 'w') as f:
            f.write('a.txt')
        self.move_a(is_dry_run=False)
        self.assertIn('0 to copy, 1 there already', self.printed())
        self.assertEqual(self.sorter.changes.summary(self.mirror), '')

    def test_with_none_picked_nothing_else_changes(self):
        self.sort([['a.txt'], None], [MOVE, YES], dirs=[os.path.join(self.root, 'docs')], is_dry_run=False)
        self.assertFalse(os.path.exists(os.path.join(self.mirror, 'docs')))


class ChoosingTest(InboxSortTest):
    def setUp(self):
        super().setUp()
        self.mirror = os.path.join(self.tmpdir, 'mirror')
        os.makedirs(self.mirror)
        self.known = replicas.Replicas()
        self.known.record(self.root, self.mirror)

    def choose(self, answers):
        with helpers.answering_option_picker(answers) as pick_option:
            chosen = followers.choose(self.known, self.inbox, self.root)
        return chosen, pick_option

    def test_none_is_picked_unless_the_user_picks_it(self):
        chosen, pick_option = self.choose(["Go on"])
        self.assertEqual(chosen, [])
        options = pick_option.call_args.args[0]
        self.assertIn(followers.choice.NOT_PICKED_MARK + self.mirror, [picker.option_label(option) for option in options])

    def test_a_picked_one_is_returned_and_remembered(self):
        chosen, _ = self.choose([followers.choice.NOT_PICKED_MARK + self.mirror, "Go on"])
        self.assertEqual(chosen, [self.mirror])
        self.assertEqual(self.known.followers_of(self.root)[0], self.mirror)

    def test_picking_it_again_unpicks_it(self):
        chosen, _ = self.choose([followers.choice.NOT_PICKED_MARK + self.mirror,
                                 followers.choice.PICKED_MARK + self.mirror, "Go on"])
        self.assertEqual(chosen, [])

    def test_with_none_known_nothing_is_asked(self):
        with mock.patch('dirdelta.ui.picker.pick_option') as pick_option:
            self.assertEqual(followers.choose(replicas.Replicas(), self.inbox, self.root), [])
        pick_option.assert_not_called()

    def test_one_not_there_cant_be_picked(self):
        self.assertEqual(followers.cant_follow(self.root, os.path.join(self.tmpdir, 'gone')), "not there: not mounted?")
        self.assertIsNotNone(followers.cant_follow('cloud/me', 'cloud/other'))
        self.assertIsNone(followers.cant_follow(self.root, 'cloud/me'))

    def test_quitting_it_doesnt_sort(self):
        with helpers.answering_option_picker([None]), mock.patch.object(Sort, 'run') as run:
            inbox.run(self.inbox, self.root, self.known)
        run.assert_not_called()
