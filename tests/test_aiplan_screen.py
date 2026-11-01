import os
import threading
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
                              ('pick', mock.patch('dirdelta.picker.pick_files')),
                              ('line', mock.patch('dirdelta.messages.print_line')),
                              ('progress', mock.patch('dirdelta.messages.print_progress'))):
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

    def test_an_answer_is_shown_and_theres_nothing_to_review(self):
        self.make.return_value = aiplan.Plan('', [], [], 'It has two photos.')
        self.assertEqual(aiplan_screen.ask(TASK), ('do it', None))
        self.assertEqual(self.show.call_args.args[:2], ('The AI says', ['It has two photos.']))
        self.pick.assert_not_called()

    def test_a_long_answer_takes_several_screens(self):
        self.make.return_value = aiplan.Plan('', [], [], '\n'.join(str(number) for number in range(100)))
        with mock.patch('shutil.get_terminal_size', return_value=os.terminal_size((80, 26))):
            aiplan_screen.ask(TASK)
        titles = [call.args[0] for call in self.show.call_args_list]
        self.assertEqual(titles[0], 'The AI says (1 of 5)')
        self.assertEqual(sum(len(call.args[1]) for call in self.show.call_args_list), 100)

    def test_it_says_its_waiting(self):
        is_said = threading.Event()
        self.progress.side_effect = lambda line: is_said.set()

        def make(task, instruction):
            self.assertTrue(is_said.wait(5))
            return PLAN
        self.make.side_effect = make
        self.assertEqual(aiplan_screen.ask(TASK)[1], PLAN.steps)
        self.assertIn('Waiting for the AI', self.line.call_args_list[-1].args[0])
        self.assertTrue(self.progress.call_args.args[0].startswith('Waited'))

    def test_the_screen_says_whats_read(self):
        aiplan_screen.ask(TASK)
        self.assertIn('not their contents', ' '.join(self.typed.call_args.args[1]))
        aiplan_screen.ask(TASK._replace(focus=['a.txt'], fetch=lambda relpath: None))
        self.assertIn('It may read a.txt', ' '.join(self.typed.call_args.args[1]))
        aiplan_screen.ask(TASK._replace(focus=['z.zip'], fetch=lambda relpath: None))
        said = ' '.join(self.typed.call_args.args[1])
        self.assertIn('the list of files in z.zip', said)
        self.assertNotIn('It may read', said)

    def test_too_many_isnt_asked(self):
        many = TASK._replace(files=[aiplan.File('x')] * (aiplan.MAX_FILES + 1))
        self.assertEqual(aiplan_screen.ask(many, 'before'), ('before', None))
        self.typed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
