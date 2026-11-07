"""What the sync menu's tests share: two local replicas whose ways' files are faked"""
import time
import unittest
from unittest import mock

from dirdelta.known import replicanames
from dirdelta.sync import dirsync_main
from dirdelta.sync import options as menu_options
from dirdelta.matching import differing
from dirdelta.sync import replica_ops
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker


class MainMenuTest(unittest.TestCase):
    def setUp(self):
        # The local dirs are writable unless a test says otherwise, and no message waits for Enter
        self.writable = {'/a', '/b'}
        for patcher in (mock.patch('dirdelta.known.replicanames.mounts.current_mount', return_value=None),
                        mock.patch('dirdelta.sync.replica_ops.os.access',
                                   side_effect=lambda path, mode: path in self.writable),
                        mock.patch('dirdelta.ui.messages.show')):
            self.addCleanup(patcher.stop)
            self.show = patcher.start()
        replicanames.forget()
        # Each dir's files that the other lacks: /a's 3, /b's 1
        self.missing = {'/a': ['x', 'y', 'z'], '/b': ['w']}
        self.find_missing_calls = []
        def find_missing(src, dst):
            self.find_missing_calls.append(src.fullpath())
            return replica_ops.Missing(self.missing[src.fullpath()], [])
        patcher = mock.patch('dirdelta.sync.replica_ops.find_missing', side_effect=find_missing)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The files both have that differ, /a's way (none unless a test says so)
        self.differ = {}
        # And the ones of the same size not compared (their hashes unknown), and what's compared
        self.uncompared = []
        self.compared_given = []
        def find(src, dst, compared=None):
            self.compared_given.append(dict(compared or {}))
            return differing.Changes(self.differ, self.uncompared)
        patcher = mock.patch('dirdelta.matching.differing.find', side_effect=find)
        patcher.start()
        self.addCleanup(patcher.stop)

    def shown(self, replica_a, replica_b):
        """What the main menu's options are shown as, once each way's files are found"""
        def pick_option(options, shown_as, **_):
            while any('loading' in shown for shown in shown_as().values()):
                time.sleep(0.01)
            self.shown_options = [shown_as().get(option, option) for option in options[2:]]
            self.state_line = shown_as()[menu_options.STATE]
            return dirsync_main.BACK
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option):
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        return self.shown_options

    def options(self, replica_a, replica_b):
        with mock.patch('dirdelta.ui.picker.pick_option', return_value=dirsync_main.BACK) as pick_option:
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        options, = pick_option.call_args.args
        self.assertEqual(options[:2], [picker.Option(menu_options.STATE, menu_options.STATE, picker.Skipped(menu_options.STATE)),
                                       picker.BLANK])
        return options[2:]

    def browse(self, answers, has_changed=False):
        """The main menu answering answers in turn, each way's browse() changing the replicas'
        files if has_changed; returns the syncs browsed"""
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        syncs = []

        def browse(sync):
            syncs.append(sync)
            sync.has_changed = has_changed
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.sync.way.interactive_dir_sync.InteractiveDirSync.browse', autospec=True,
                           side_effect=browse):
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(answers, [])
        return syncs
