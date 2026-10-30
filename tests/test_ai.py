import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import claude_agent_sdk

from dirdelta import ai


class _Answering(object):
    """A fake ai._run_query(): answers each request with answer(prompt, files numbered in it), and
    keeps the requests"""
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def __call__(self, prompt, readable_dirs, schema, max_turns, model, system_prompt=None):
        self.prompts.append((prompt, readable_dirs, schema))
        self.models = getattr(self, 'models', []) + [model]
        return {'files': self.answer(prompt)}


class AITest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='dirdelta-ai-')
        self.addCleanup(shutil.rmtree, self.tmpdir)
        patcher = mock.patch('dirdelta.ai.CACHE_FILE', os.path.join(self.tmpdir, 'cache', 'ai.json'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key = lambda file: 'inbox/%s\t%s' % (file.relpath, file.size)

    def files(self, count, local=True):
        return [ai.File('f%d.txt' % (i,), os.path.join(self.tmpdir, 'f%d.txt' % (i,)) if local else None, 10)
                for i in range(count)]

    def test_descriptions_in_batches_by_number_cached(self):
        answering = _Answering(lambda prompt: [
            {'number': number, 'description': 'file number %d of the batch' % (number,)}
            for number in range(1, prompt.count('. f') + 1)])
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            found = ai.describe(self.files(ai.BATCH_SIZE + 2), self.key)
        self.assertEqual(len(answering.prompts), 2)
        self.assertEqual(found['f0.txt'], 'file number 1 of the batch')
        self.assertEqual(found['f%d.txt' % (ai.BATCH_SIZE + 1,)], 'file number 2 of the batch')
        # Asked once: the cache has them
        with mock.patch('dirdelta.ai._run_query', side_effect=AssertionError('asked again')):
            self.assertEqual(ai.describe(self.files(2), self.key)['f1.txt'], 'file number 2 of the batch')
        self.assertEqual(ai.cached(self.files(1), self.key, 'root')[0], {'f0.txt': 'file number 1 of the batch'})

    def test_which_files_claude_may_read(self):
        files = [ai.File('a.txt', os.path.join(self.tmpdir, 'a.txt'), 10),
                 ai.File('b.gdoc', None, None),
                 ai.File('big.mov', os.path.join(self.tmpdir, 'sub', 'big.mov'), ai.MAX_READ_SIZE + 1)]
        answering = _Answering(lambda prompt: [])
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            ai.describe(files, self.key)
        prompt, readable_dirs, _ = answering.prompts[0]
        self.assertIn("1. a.txt (size 10 bytes): read it at %s" % (files[0].local_path,), prompt)
        self.assertIn("2. b.gdoc (size unknown, don't read it)", prompt)
        self.assertIn("3. big.mov (size %d bytes, don't read it)" % (ai.MAX_READ_SIZE + 1,), prompt)
        self.assertEqual(readable_dirs, [self.tmpdir, os.path.join(self.tmpdir, 'sub')])

    def test_descriptions_are_cut_short(self):
        answering = _Answering(lambda prompt: [{'number': 1, 'description': ' '.join(['word'] * 15) + '.'}])
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            found = ai.describe(self.files(1), self.key)
        self.assertEqual(found['f0.txt'], ' '.join(['word'] * ai.MAX_DESCRIPTION_WORDS))

    def test_recommendations_per_sorted_tree_and_cleaned(self):
        answering = _Answering(lambda prompt: [
            {'number': 1, 'action': 'move', 'path': '/lists/shopping/2026-10 groceries.txt', 'reason': 'a list'},
            {'number': 2, 'action': 'move', 'path': '../outside/f1.txt', 'reason': 'no'},
            {'number': 3, 'action': 'move', 'path': 'top', 'reason': 'top level'}])
        dirs = {'': ['notes.txt'], 'lists': ['2026-09 groceries.txt'], 'photos/2024': []}
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            found = ai.recommend(self.files(3), self.key, dirs, 'cloud/me', {'f0.txt': 'a shopping list'})
        self.assertEqual(found['f0.txt'], {'action': 'move', 'path': 'lists/shopping/2026-10 groceries.txt',
                                           'reason': 'a list', 'copies': []})
        self.assertNotIn('f1.txt', found)
        # A new name without the file's extension gets it
        self.assertEqual(found['f2.txt']['path'], 'top.txt')
        prompt, readable_dirs, schema = answering.prompts[0]
        self.assertIn("The sorted tree's dirs:\n. (the root) (e.g. notes.txt)\nlists (e.g. 2026-09 groceries.txt)\n"
                      "photos/2024", prompt)
        # By the descriptions: nothing's read
        self.assertIn("1. f0.txt (size 10 bytes): a shopping list", prompt)
        self.assertEqual(readable_dirs, [])
        self.assertEqual(schema['properties']['files']['items']['required'], ['number', 'action', 'path', 'reason'])
        self.assertEqual(schema['properties']['files']['items']['properties']['action']['enum'], ['move', 'remove'])
        self.assertEqual(ai.cached(self.files(1), self.key, 'cloud/me')[1]['f0.txt']['path'],
                         'lists/shopping/2026-10 groceries.txt')
        # Another sorted tree isn't the same recommendation
        self.assertEqual(ai.cached(self.files(1), self.key, 'cloud/other')[1], {})

    def test_a_copy_or_junk_may_be_recommended_to_be_removed(self):
        answering = _Answering(lambda prompt: [
            {'number': 1, 'action': 'remove', 'path': '', 'reason': 'a copy'},
            # Not a copy: junk, as Claude says (no copies)
            {'number': 2, 'action': 'remove', 'path': '', 'reason': 'an empty file'}])
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            found = ai.recommend(self.files(2), self.key, {}, 'root', {}, {'f0.txt': ['docs/f0.txt']})
        self.assertEqual(found, {'f0.txt': {'action': 'remove', 'path': '', 'reason': 'a copy',
                                            'copies': ['docs/f0.txt']},
                                 'f1.txt': {'action': 'remove', 'path': '', 'reason': 'an empty file',
                                            'copies': []}})
        self.assertIn("clearly junk", answering.prompts[0][0])
        self.assertIn("1. f0.txt (size 10 bytes); already in the sorted tree, with the same contents, at docs/f0.txt",
                      answering.prompts[0][0])
        self.assertIsNone(ai.recommended_path('f0.txt', found['f0.txt']))
        # A file found to be a copy since is asked about again
        with mock.patch('dirdelta.ai._run_query', side_effect=AssertionError('asked again')):
            ai.recommend(self.files(1), self.key, {}, 'root', {}, {'f0.txt': ['docs/f0.txt']})
        answering = _Answering(lambda prompt: [{'number': 1, 'action': 'move', 'path': 'a/f0.txt', 'reason': ''}])
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            ai.recommend(self.files(1), self.key, {}, 'root', {}, {'f0.txt': ['docs/f0.txt', 'other/f0.txt']})
        self.assertEqual(len(answering.prompts), 1)

    def test_haiku_describes_and_recommends(self):
        answering = _Answering(lambda prompt: [])
        with mock.patch('dirdelta.ai._run_query', side_effect=answering):
            ai.describe(self.files(1), self.key)
            ai.recommend(self.files(1), self.key, [], 'root', {})
        self.assertEqual(answering.models, ['claude-haiku-5-5', 'claude-haiku-5-5'])

    def test_a_recommendation_cached_with_a_dir_only_is_the_files_name_there(self):
        self.assertEqual(ai.recommended_path('in/a.txt', {'destination': 'docs'}), 'docs/a.txt')
        self.assertEqual(ai.recommended_path('a.txt', {'destination': ''}), 'a.txt')
        self.assertEqual(ai.recommended_path('a.txt', {'path': 'docs/b.txt'}), 'docs/b.txt')

    def test_what_the_cache_has_goes_with_the_files(self):
        with mock.patch('dirdelta.ai._run_query', side_effect=_Answering(
                lambda prompt: [{'number': 1, 'description': 'a list'}])):
            ai.describe(self.files(1), self.key)
        ai.carry({self.key(self.files(1)[0]): 'sorted/f0.txt\t10', 'nothing\t1': 'else\t1'})
        moved = ai.File('f0.txt', None, 10)
        self.assertEqual(ai.cached([moved], lambda file: 'sorted/f0.txt\t10', 'root')[0], {'f0.txt': 'a list'})
        self.assertEqual(ai.cached([moved], lambda file: 'else\t1', 'root')[0], {})

    def test_a_failed_batch_is_asked_again_a_file_at_a_time(self):
        def run_query(prompt, readable_dirs, schema, max_turns, model, system_prompt=None):
            if 'f1.txt' in prompt:
                raise ai.AIError('too big')
            return {'files': [{'number': 1, 'description': 'fine'}]}
        with mock.patch('dirdelta.ai._run_query', side_effect=run_query) as query:
            found = ai.describe(self.files(3), self.key)
        self.assertEqual(found, {'f0.txt': 'fine', 'f2.txt': 'fine'})
        self.assertEqual(query.call_count, 4)
        # All of them failing is an error
        with mock.patch('dirdelta.ai._run_query', side_effect=ai.AIError('not logged in')), \
                self.assertRaises(ai.AIError):
            ai.describe(self.files(2)[1:], self.key)

    def test_progress(self):
        progress = []
        with mock.patch('dirdelta.ai._run_query', side_effect=_Answering(lambda prompt: [])):
            ai.describe(self.files(ai.BATCH_SIZE + 1), self.key, lambda *args: progress.append(args))
        self.assertEqual(progress, [(0, ai.BATCH_SIZE + 1), (ai.BATCH_SIZE, ai.BATCH_SIZE + 1),
                                    (ai.BATCH_SIZE + 1, ai.BATCH_SIZE + 1)])


class _Result(object):
    def __init__(self, subtype='success', structured_output=None):
        self.subtype = subtype
        self.structured_output = structured_output


class RunQueryTest(unittest.TestCase):
    def run_query(self, results):
        self.calls = []

        async def query(prompt, options):
            self.calls.append((prompt, options))
            for result in results:
                yield result
        with mock.patch.object(claude_agent_sdk, 'query', query), \
                mock.patch.object(claude_agent_sdk, 'ResultMessage', _Result):
            return ai._run_query('the prompt', ['/in', '/in/sub'], {'type': 'object'}, 7, 'the-model')

    def test_with_nothing_to_read_claude_gets_no_tools(self):
        async def query(prompt, options):
            self.options = options
            yield _Result(structured_output={'files': []})
        with mock.patch.object(claude_agent_sdk, 'query', query), \
                mock.patch.object(claude_agent_sdk, 'ResultMessage', _Result):
            ai._run_query('the prompt', [], {'type': 'object'}, 5, 'the-model', system_prompt='sorting')
        self.assertEqual((self.options.tools, self.options.allowed_tools), ([], []))
        self.assertEqual(self.options.system_prompt, 'sorting')

    def test_claude_may_only_read_and_answers_by_the_schema(self):
        self.assertEqual(self.run_query([_Result(structured_output={'files': []})]), {'files': []})
        prompt, options = self.calls[0]
        self.assertEqual(prompt, 'the prompt')
        self.assertEqual(options.tools, ['Read'])
        self.assertEqual(options.allowed_tools, ['Read'])
        self.assertEqual(options.permission_mode, 'dontAsk')
        self.assertEqual(options.setting_sources, [])
        self.assertEqual((options.cwd, options.add_dirs), ('/in', ['/in/sub']))
        self.assertEqual(options.max_turns, 7)
        self.assertEqual(options.model, 'the-model')
        self.assertEqual(options.output_format, {'type': 'json_schema', 'schema': {'type': 'object'}})
        # A read file's message may be big; Claude Code's stderr isn't printed
        self.assertEqual(options.max_buffer_size, ai.MAX_MESSAGE_SIZE)
        self.assertTrue(callable(options.stderr))

    def test_the_sdks_errors_arent_printed_but_said(self):
        import logging

        async def query(prompt, options):
            logging.getLogger('claude_agent_sdk._internal.query').error('Fatal error in message reader: too big')
            options.stderr('the last line')
            raise RuntimeError('Command failed')
            yield
        with mock.patch.object(claude_agent_sdk, 'query', query), \
                mock.patch.object(claude_agent_sdk, 'ResultMessage', _Result), \
                mock.patch('sys.stderr') as stderr:
            with self.assertRaises(ai.AIError) as raised:
                ai._run_query('the prompt', [], {'type': 'object'}, 5, 'the-model')
        self.assertEqual(str(raised.exception), 'Claude failed: Command failed (Fatal error in message reader: too big)')
        stderr.write.assert_not_called()
        self.assertFalse(logging.getLogger('claude_agent_sdk').propagate)


    def test_no_answer_is_an_error(self):
        with self.assertRaises(ai.AIError):
            self.run_query([_Result('error_max_structured_output_retries')])
        with self.assertRaises(ai.AIError):
            self.run_query([])


if __name__ == '__main__':
    unittest.main()
