import unittest
from unittest import mock

from dirdelta import ai
from dirdelta import aiplan
from dirdelta import aiplan_screen
from dirdelta import picker

TASK = aiplan.Task('Some files.', [aiplan.File('a.txt'), aiplan.File('b.txt')],
                   [aiplan.Action('copy', 'Copy', 'copy it.'), aiplan.Action('move', 'Move', 'move it.', True)])
PLAN = aiplan.Plan('Copy one, move one', [aiplan.Step('copy', 'a.txt', None, 'wanted'),
                                          aiplan.Step('move', 'b.txt', 'x/b.txt', 'neater')], [])


class AskTest(unittest.TestCase):
    def setUp(self):
        for name, patcher in (('show', mock.patch('dirdelta.messages.show')),
                              ('typed', mock.patch('dirdelta.messages.ask', return_value='do it')),
                              ('make', mock.patch('dirdelta.aiplan.make', return_value=PLAN)),
                              ('pick', mock.patch('dirdelta.picker.pick_files'))):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.pick.side_effect = lambda root, items, **_: picker.Picked('', '', list(items))

    def test_the_steps_left_picked(self):
        self.assertEqual(aiplan_screen.ask(TASK), ('do it', PLAN.steps))
        self.assertEqual(self.pick.call_args.kwargs['picked'], ['Copy/a.txt', 'Move/b.txt'])

    def test_unpicked_ones_arent_returned(self):
        self.pick.side_effect = lambda root, items, **_: picker.Picked('', '', ['Move/b.txt'])
        self.assertEqual(aiplan_screen.ask(TASK)[1], PLAN.steps[1:])

    def test_quitting_the_review(self):
        self.pick.side_effect = lambda root, items, **_: None
        self.assertEqual(aiplan_screen.ask(TASK), ('do it', None))

    def test_typing_nothing_keeps_what_it_started_from(self):
        self.typed.return_value = None
        self.assertEqual(aiplan_screen.ask(TASK, 'before'), ('before', None))
        self.make.assert_not_called()

    def test_a_failure_is_said(self):
        self.make.side_effect = ai.AIError("no Claude")
        self.assertEqual(aiplan_screen.ask(TASK), ('do it', None))
        self.assertIn("no Claude", self.show.call_args.args[1][0])
        self.pick.assert_not_called()

    def test_no_steps_says_why(self):
        self.make.return_value = aiplan.Plan('Nothing fits', [], [])
        self.assertEqual(aiplan_screen.ask(TASK), ('do it', None))
        self.assertEqual(self.show.call_args.args[1], ['Nothing fits'])

    def test_whats_left_out_is_said(self):
        self.make.return_value = PLAN._replace(left_out=[('copy z', 'no such file')])
        aiplan_screen.ask(TASK)
        self.assertIn('  copy z: no such file', self.show.call_args.args[1])

    def test_too_many_isnt_asked(self):
        many = TASK._replace(files=[aiplan.File('x')] * (aiplan.MAX_FILES + 1))
        self.assertEqual(aiplan_screen.ask(many, 'before'), ('before', None))
        self.typed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
