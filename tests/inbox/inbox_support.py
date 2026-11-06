"""What the inbox sort's tests share: a local inbox and sorted tree, and the sort run with scripted answers"""
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import inbox
from dirdelta.claude import ai
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.ui import sidetree


Sort = inbox.InboxSort
NOTHING = Sort.NOTHING
YES = Sort.CONFIRM_YES
NO = Sort.CONFIRM_NO
SURE = Sort.CONFIRM_SURE


class InboxSortTest(unittest.TestCase):
    """A local inbox with a.txt, b.jpg and trip/c.jpg; a sorted tree with docs/ and photos/"""

    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-inbox-'))
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.inbox = os.path.join(self.tmpdir, 'inbox')
        self.root = os.path.join(self.tmpdir, 'sorted')
        helpers.make_files(self.inbox, ['a.txt', 'b.jpg', 'trip/c.jpg'])
        helpers.make_files(self.root, ['docs/old.txt', 'photos/old.jpg'])
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'),
                        mock.patch('dirdelta.ui.messages.print_progress'),
                        mock.patch('dirdelta.ui.messages.show'),
                        mock.patch('dirdelta.claude.ai.config.CACHE_FILE', os.path.join(self.tmpdir, 'ai.json'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show = messages.show

    def synchronously(self):
        """Patch InboxSort.ask_in_background to wait for what it asks Claude, so a test sees it done"""
        ask = Sort.ask_in_background

        def ask_and_wait(sorter, relpaths, place=True, anew=False):
            ask(sorter, relpaths, place, anew)
            sorter.wait_for_claude()
        return mock.patch.object(Sort, 'ask_in_background', ask_and_wait)

    def sort(self, picks, answers, dirs=(), view=True, is_dry_run=False, known=None):
        """Sort, the inbox's picker answering picks in turn, the menus answers, the dir picker
        dirs (paths), and the approval's view returning view"""
        picks, dirs = list(picks), list(dirs)
        with helpers.scripted_files_picker(lambda relpaths: picks.pop(0)) as self.pick_files, \
                helpers.answering_option_picker(answers) as self.pick_option, \
                mock.patch('dirdelta.ui.picker.pick_under_dir',
                           side_effect=lambda *_, **__: self.picked_dir(dirs.pop(0))) as self.pick_under_dir, \
                mock.patch('dirdelta.ui.picker.view_files', return_value=view) as self.view_files, \
                mock.patch('dirdelta.util.dryrun.DRYRUN', is_dry_run), self.synchronously():
            self.sorter = Sort(self.inbox, self.root, known)
            self.sorter.run()

    @staticmethod
    def picked_dir(picked):
        """What the dir picker returns for picked: a path (Enter on it), or (a key, the path)"""
        return picked if isinstance(picked, tuple) else ('', picked)

    def exists(self, *parts):
        return os.path.exists(os.path.join(self.tmpdir, *parts))

    def fake_gio_trash(self):
        """Patch subprocess.run so gio trash moves the file into self.trash (anything else runs)"""
        self.trash = os.path.join(self.tmpdir, 'trash')
        os.makedirs(self.trash)
        real_run = subprocess.run

        def run(command, *args, **kwargs):
            if command[:2] == ['gio', 'trash']:
                shutil.move(command[2], self.trash)
                return subprocess.CompletedProcess(command, 0, stdout='')
            return real_run(command, *args, **kwargs)
        return mock.patch('subprocess.run', side_effect=run)

    def ask_ai(self, steps, picks, answers=()):
        """Sort, the inbox's picker answering picks, then the review keeping all, the AI answering steps"""
        picks = list(picks)

        def pick_files(root, items, **_):
            if root == "The AI's plan":
                self.reviewed = list(items)
                return picker.Picked('', '', list(items))
            chosen = picks.pop(0)
            return picker.Picked('', '', chosen) if isinstance(chosen, list) else chosen
        with mock.patch('dirdelta.claude.ai.query.run_query', return_value={'summary': 'ok', 'steps': steps}), \
                mock.patch('dirdelta.ui.messages.ask', return_value='sort them'), \
                mock.patch('dirdelta.ui.picker.pick_files', side_effect=pick_files), \
                helpers.answering_option_picker(answers), mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.trees.localdiskdirtree.LocalReplica.trashing', return_value=contextlib.nullcontext()), \
                mock.patch('dirdelta.ui.picker.view_files') as self.view_files:
            self.sorter = Sort(self.inbox, self.root)
            self.sorter.run()

    def refreshed(self, pick):
        """How many times the side tree's listed in a sort with pick, then quitting, and the picks after pick"""
        sorter = Sort(self.inbox, self.root)
        with mock.patch('dirdelta.ui.sidetree._listed', wraps=sidetree._listed) as listed, \
                mock.patch('dirdelta.ui.picker.pick_files', side_effect=[pick, None]) as pick_files, \
                mock.patch('dirdelta.sync.replica_ops.refresh_replica') as self.refresh_replica:
            sorter.run()
        return listed.call_count, pick_files.call_args_list[-1].kwargs['picked']

    def drive_inbox(self):
        """A sort whose inbox is on Drive as far as _ai_files() can tell, with a.txt, b.jpg and trip/c.jpg"""
        sorter = Sort(self.inbox, self.root)
        sorter.inbox_is_cloud = True
        sorter._inbox_tree = mock.MagicMock()
        sorter._inbox_tree.__contains__.side_effect = lambda relpath: relpath in ('a.txt', 'b.jpg', 'trip/c.jpg')
        sorter._inbox_tree.file_size.return_value = 1
        sorter._inbox_tree.cant_fetch.return_value = None
        return sorter

    def read_only_inbox(self):
        patcher = mock.patch('dirdelta.sync.replica_ops.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.inbox))
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_only_root(self):
        patcher = mock.patch('dirdelta.sync.replica_ops.is_writable', side_effect=lambda tree: tree.fullpath() != os.path.realpath(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask_claude(self, answers):
        """Patch ai.query.run_query to answer with answers ({relpath: {field: value}}) for the files in its
        prompt, the fields its schema asks for; its calls are self.queries"""
        self.queries = []

        def run_query(prompt, readable_dirs, schema, max_turns, model, system_prompt=None):
            fields = schema['properties']['files']['items']['required'][1:]
            self.queries.append((fields, model, prompt))
            lines = prompt.split('The files')[1].split(':\n', 1)[1].split('\n\n')[0].splitlines()
            relpaths = [line.split('. ', 1)[1].split(' (')[0] for line in lines]
            return {'files': [dict({field: answers[relpath][field] for field in fields}, number=number)
                              for number, relpath in enumerate(relpaths, 1)]}
        return mock.patch('dirdelta.claude.ai.query.run_query', side_effect=run_query)

    def claude_places(self):
        return self.ask_claude({'a.txt': {'description': 'a list', 'action': 'move', 'path': 'docs/a.txt',
                                          'reason': 'a document'},
                                'b.jpg': {'description': 'a cat', 'action': 'move', 'path': 'photos/cats/b.jpg',
                                          'reason': 'a cat photo'},
                                'trip/c.jpg': {'description': 'a beach', 'action': 'move',
                                               'path': 'photos/trips/2024/beach.jpg', 'reason': 'a trip photo'}})

    def sent_previews(self, pick_files_call):
        """What a picker's previews sent it first (then the picker is gone)"""
        sent = {}

        def send(found=None, default=None):
            if sent:
                raise picker.PickerClosed()
            sent.update(found or {})
        with self.assertRaises(picker.PickerClosed):
            pick_files_call.kwargs['previews'](send)
        return sent

    def copy_in_the_inbox(self):
        """An inbox file with the same name and contents as the sorted tree's docs/old.txt"""
        with open(os.path.join(self.inbox, 'old.txt'), 'w') as f:
            f.write('docs/old.txt')

    def two_trees(self):
        """The sort with a tree each (as a local inbox and a Drive sorted tree have), both local
        here, so the copy-then-remove path is run without Drive"""
        sorter = Sort(self.inbox, self.root)
        sorter.is_same_kind = False
        return sorter

    def claude_on_dirs(self, dir_answer, description='a beach at sunset'):
        """Patch Claude: files described as description, a dir answered dir_answer; its calls are
        the mock's"""
        def query(prompt, readable_dirs, schema, max_turns, model, system_prompt=ai.SYSTEM_PROMPT):
            if system_prompt == ai.DIR_SYSTEM_PROMPT:
                return dir_answer
            return {'files': [{'number': number, 'description': description}
                              for number in range(1, prompt.count('size ') + 1)]}
        return mock.patch('dirdelta.claude.ai.query.run_query', side_effect=query)

    def cache_dir_recommendation(self, dirpath, recommendation):
        """Put what Claude said of the inbox's dir in its cache, as asked before"""
        sorter = Sort(self.inbox, self.root)
        files = sorter._inbox_files()
        key = sorter._dir_key(dirpath, *sorter._dir_stats(files)[dirpath])
        with open(ai.config.CACHE_FILE, 'w') as f:
            json.dump({key: {'recommendations': {sorter.root_path: recommendation}}}, f)


if __name__ == '__main__':
    unittest.main()
