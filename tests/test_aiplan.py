import unittest
from unittest import mock

from dirdelta import ai
from dirdelta import aiplan

COPY = aiplan.Action('copy', 'Copy', 'copy it.')
MOVE = aiplan.Action('move', 'Move', 'move it.', True, False,
                     lambda relpath, target: "taken" if target == 'taken.txt' else None)
RENAME_OTHER = aiplan.Action('rename other', 'Rename other', 'rename it.', True, True)
TASK = aiplan.Task('Some files.', [aiplan.File('a.txt', 3, 'a note'), aiplan.File('d/b.txt')],
                   [COPY, MOVE, RENAME_OTHER], ['other.txt'], ['Some context.'])


def plan(*steps, task=TASK):
    with mock.patch('dirdelta.ai._run_query', return_value={'summary': ' done ', 'steps': list(steps)}):
        return aiplan.make(task, 'do it')


class MakeTest(unittest.TestCase):
    def test_the_steps_in_the_order_of_the_actions(self):
        made = plan({'action': 'move', 'number': 2, 'path': 'x/b', 'reason': ' why '}, {'action': 'copy', 'number': 1})
        self.assertEqual(made.summary, 'done')
        self.assertEqual(made.steps, [aiplan.Step('copy', 'a.txt', None, ''), aiplan.Step('move', 'd/b.txt', 'x/b.txt', 'why')])
        self.assertEqual(made.left_out, [])

    def test_an_others_action_goes_by_the_others_numbers(self):
        made = plan({'action': 'rename other', 'number': 3, 'path': 'y.txt'}, {'action': 'rename other', 'number': 1, 'path': 'z'})
        self.assertEqual(made.steps, [aiplan.Step('rename other', 'other.txt', 'y.txt', '')])
        self.assertEqual(len(made.left_out), 1)

    def assert_left_out(self, *steps):
        made = plan(*steps)
        self.assertEqual(made.steps[1:] if len(steps) > 1 else made.steps, [])
        self.assertEqual(len(made.left_out), 1, made.left_out)

    def test_what_cant_be_done_is_left_out(self):
        for step in ({'action': 'delete everything', 'number': 1},
                     {'action': 'copy', 'number': 0},
                     {'action': 'copy', 'number': 3},
                     {'action': 'copy', 'number': True},
                     {'action': 'copy', 'number': '1'},
                     {'action': 'move', 'number': 1},
                     {'action': 'move', 'number': 1, 'path': '../out.txt'},
                     {'action': 'move', 'number': 1, 'path': 'a.txt'},
                     {'action': 'move', 'number': 1, 'path': 'taken.txt'},
                     {'action': 'move', 'number': 1, 'path': 'meta/x.txt'}):
            self.assert_left_out(step)

    def test_a_file_has_one_step(self):
        self.assert_left_out({'action': 'copy', 'number': 1}, {'action': 'move', 'number': 1, 'path': 'x.txt'})

    def test_two_files_dont_go_to_one_path(self):
        self.assert_left_out({'action': 'move', 'number': 1, 'path': 'x.txt'}, {'action': 'move', 'number': 2, 'path': 'x.txt'})

    def test_the_prompt_says_what_its_told(self):
        with mock.patch('dirdelta.ai._run_query', return_value={'summary': '', 'steps': []}) as query:
            aiplan.make(TASK, 'do it')
        prompt = query.call_args.args[0]
        for said in ('do it', 'Some files.', '1. a.txt (3 bytes): a note', '2. d/b.txt (size unknown)', '3. other.txt',
                     'Some context.'):
            self.assertIn(said, prompt)
        self.assertEqual(query.call_args.kwargs['model'], ai.PLAN_MODEL)

    def test_too_many(self):
        self.assertFalse(aiplan.too_many(TASK))
        self.assertTrue(aiplan.too_many(TASK._replace(files=[aiplan.File('x')] * (aiplan.MAX_FILES + 1))))


if __name__ == '__main__':
    unittest.main()
