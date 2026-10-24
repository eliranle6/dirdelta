import unittest
from unittest import mock

from dirdelta import dirsync_main
from dirdelta import dirtree
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree


class ScanErrorsWarningTest(unittest.TestCase):
    def warning(self, scan_errors):
        tree = dirtree.DirTree('/some/dir')
        tree.scan_errors = scan_errors
        return dirsync_main.scan_errors_warning(tree)

    def test_no_errors_no_warning(self):
        self.assertEqual(self.warning([]), [])

    def test_trees_without_scan_errors_get_no_warning(self):
        # E.g. cloud trees, which aren't scanned with find
        self.assertEqual(dirsync_main.scan_errors_warning(dirtree.DirTree('cloud/mein')), [])

    def test_errors_are_listed(self):
        self.assertEqual(self.warning(["find: '/some/dir/a': Permission denied"]), [
            "find couldn't read everything in /some/dir (1 errors), so the diff may be wrong:",
            "  find: '/some/dir/a': Permission denied",
        ])

    def test_only_the_first_errors_are_listed(self):
        lines = self.warning(["find: '/some/dir/%d': Permission denied" % (i,) for i in range(5)])
        self.assertEqual(len(lines), 1 + dirsync_main.MAX_SCAN_ERRORS_SHOWN + 1)
        self.assertIn('(5 errors)', lines[0])
        self.assertEqual(lines[-1], '  (and 2 more)')


class MainMenuTest(unittest.TestCase):
    def options(self, replica_a, replica_b):
        with mock.patch('dirdelta.picker.pick_option', return_value='Quit') as pick_option:
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        options, = pick_option.call_args.args
        return options

    def test_local_dirs_get_copy_and_remove_each_way(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.options(a, b), [
            'Copy files from /a to /b (the ones it lacks)',
            'Copy files from /b to /a (the ones it lacks)',
            'Remove files from /a (the ones /b lacks)',
            'Remove files from /b (the ones /a lacks)',
            'Quit',
        ])

    def test_a_cloud_replica_gets_viewing_only(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        self.assertEqual(self.options(a, b), [
            'View files in /a, not /b',
            'View files in /b, not /a',
            'Quit',
        ])

    def test_the_chosen_action_runs_and_the_menu_comes_back(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Remove files from /b (the ones /a lacks)', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.interactive_dir_sync.InteractiveDirSync.sync') as sync:
            dirsync_main._sync(a, b, '/a', '/b')
        sync.assert_called_once_with(interactive_dir_sync.InteractiveDirSync.REMOVE)
        self.assertEqual(answers, [])

    def test_quitting_the_menu_ends(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        with mock.patch('dirdelta.picker.pick_option', return_value=None) as pick_option:
            dirsync_main._sync(a, b, '/a', '/b')
        pick_option.assert_called_once()
