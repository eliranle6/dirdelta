import concurrent.futures
import time
import unittest
from unittest import mock

from dirdelta import clouddirtree
from dirdelta import dirsync_main
from dirdelta import dirtree
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree
from dirdelta import picker
from dirdelta import replicas


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
        self.assertEqual(len(lines), 1 + localdiskdirtree.MAX_SCAN_ERRORS_SHOWN + 1)
        self.assertIn('(5 errors)', lines[0])
        self.assertEqual(lines[-1], '  (and 2 more)')


class MainMenuTest(unittest.TestCase):
    def setUp(self):
        # The local dirs are writable unless a test says otherwise, and no message waits for Enter
        self.writable = {'/a', '/b'}
        for patcher in (mock.patch('dirdelta.dirsync_main.os.access',
                                   side_effect=lambda path, mode: path in self.writable),
                        mock.patch('dirdelta.messages.show')):
            self.addCleanup(patcher.stop)
            self.show = patcher.start()
        # Each dir's files that the other lacks: /a's 3, /b's 1
        self.missing = {'/a': ['x', 'y', 'z'], '/b': ['w']}
        self.find_missing_calls = []
        def find_missing(src, dst):
            self.find_missing_calls.append(src.fullpath())
            return interactive_dir_sync.Missing(self.missing[src.fullpath()], [])
        patcher = mock.patch('dirdelta.interactive_dir_sync.find_missing', side_effect=find_missing)
        patcher.start()
        self.addCleanup(patcher.stop)

    def shown(self, replica_a, replica_b):
        """What the main menu's options are shown as, once each way's files are found"""
        def pick_option(options, shown_as):
            while any('loading' in shown for shown in shown_as().values()):
                time.sleep(0.01)
            self.shown_options = [shown_as().get(option, option) for option in options]
            return 'Quit'
        with mock.patch('dirdelta.picker.pick_option', side_effect=pick_option):
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        return self.shown_options

    def options(self, replica_a, replica_b):
        with mock.patch('dirdelta.picker.pick_option', return_value='Quit') as pick_option:
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        options, = pick_option.call_args.args
        return options

    def test_local_dirs_get_copy_and_remove_each_way(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.options(a, b), [
            'Copy files from /a to /b',
            'Copy files from /b to /a',
            'Remove files from /a',
            'Remove files from /b',
            'Quit',
        ])

    def test_a_cloud_replica_gets_copy_and_remove_each_way(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        self.assertEqual(self.options(a, b), [
            'Copy files from /a to /b',
            'Copy files from /b to /a',
            'Remove files from /a',
            'Remove files from /b',
            'Quit',
        ])

    def test_two_cloud_replicas_get_remove_only(self):
        # Copying within Drive isn't done
        self.assertEqual(self.options(dirtree.DirTree('cloud/a'), dirtree.DirTree('cloud/b')), [
            'Remove files from /a',
            'Remove files from /b',
            'Quit',
        ])

    def test_a_cloud_replica_can_be_refreshed_from_drive(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        self.assertEqual(self.options(a, b)[-2:], ['Refresh /b from Google Drive', 'Quit'])

    def test_a_refresh_finds_each_ways_files_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        answers = ['Refresh /b from Google Drive', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(b, 'refresh_from_drive') as refresh:
            dirsync_main._sync(a, b, '/a', '/b')
        refresh.assert_called_once_with('')
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])

    def test_a_failed_refresh_says_why_and_finds_nothing_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        answers = ['Refresh /b from Google Drive', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(b, 'refresh_from_drive', side_effect=OSError('no network')):
            dirsync_main._sync(a, b, '/a', '/b')
        title, lines, _, _ = self.show.call_args.args
        self.assertEqual(title, 'Refresh cloud/b from Google Drive')
        self.assertEqual(lines, ["Couldn't refresh it: no network"])
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])

    def test_a_refresh_in_the_file_picker_finds_each_ways_files_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        answers = ['Remove files from /b', 'Quit']
        def sync(self_, action):
            self_.was_refreshed = True
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.interactive_dir_sync.InteractiveDirSync.sync', autospec=True,
                           side_effect=sync):
            dirsync_main._sync(a, b, '/a', '/b')
        # A dry run, but the trees changed
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])

    def test_a_read_only_dir_gets_nothing_copied_into_or_removed_from_it(self):
        self.writable = {'/b'}
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.options(a, b), [
            'Copy files from /a to /b',
            'Remove files from /b',
            'Quit',
        ])

    def test_read_only_replicas_are_said_to_be_before_the_menu(self):
        self.writable = set()
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        self.assertEqual(self.options(a, b), [
            'Copy files from /a to /b',
            'Remove files from /b',
            'Quit',
        ])
        title, lines, _ = self.show.call_args.args
        self.assertEqual(title, 'Read-only')
        self.assertEqual(len(lines), 1)
        self.assertIn('/a is read-only', lines[0])

    def test_writable_replicas_get_no_read_only_message(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.options(a, b)
        self.show.assert_not_called()

    def test_the_chosen_action_runs_and_the_menu_comes_back(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Remove files from /b', 'Quit']
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

    def test_options_say_how_many_files_they_are_about(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b), [
            'Copy files from /a to /b (the 3 files it lacks)',
            'Copy files from /b to /a (the 1 file it lacks)',
            'Remove files from /a (the 3 files /b lacks)',
            'Remove files from /b (the 1 file /a lacks)',
            'Quit',
        ])

    def test_view_options_say_how_many_files_too(self):
        self.writable = set()
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b), [
            'View files in /a, not /b (3 files)',
            'View files in /b, not /a (1 file)',
            'Quit',
        ])

    def test_options_with_nothing_to_do_cant_be_picked(self):
        self.missing['/b'] = []
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b), [
            'Copy files from /a to /b (the 3 files it lacks)',
            picker.Disabled('Copy files from /b to /a: nothing to copy, it has them all'),
            'Remove files from /a (the 3 files /b lacks)',
            picker.Disabled('Remove files from /b: nothing to remove, /a has them all'),
            'Quit',
        ])

    def test_a_view_option_with_nothing_to_view_cant_be_picked(self):
        self.writable = set()
        self.missing['/a'] = []
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b)[0],
                         picker.Disabled('View files in /a, not /b: nothing to view, /b has them all'))

    def test_options_are_loading_until_their_files_are_found(self):
        way = dirsync_main._Way(None, None)
        way.missing = concurrent.futures.Future()
        action = dirsync_main._Action('Copy', way, lambda count: '%d files' % (count,), 'none')
        shown = set()
        for now in (0, 0.4, 0.8, 1.2, 1.6):
            with mock.patch('dirdelta.dirsync_main.time.monotonic', return_value=now + 0.1):
                shown.add(action.shown_as())
        self.assertEqual(shown, {'Copy (loading)', 'Copy (loading.)', 'Copy (loading..)',
                                 'Copy (loading...)'})
        way.missing.set_result(interactive_dir_sync.Missing(['x'], []))
        self.assertEqual(action.shown_as(), 'Copy (1 files)')

    def test_an_option_whose_files_couldnt_be_found_says_so(self):
        way = dirsync_main._Way(None, None)
        way.missing = concurrent.futures.Future()
        way.missing.set_exception(RuntimeError('dirdiff failed'))
        action = dirsync_main._Action('Copy', way, lambda count: '%d files' % (count,), 'none')
        self.assertEqual(action.shown_as(), "Copy (couldn't count the files)")

    def test_actions_use_the_files_found_in_the_background(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Copy files from /a to /b', 'Remove files from /a', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.picker.pick_files', return_value=None) as pick_files:
            dirsync_main._sync(a, b, '/a', '/b')
        # A dry run changes nothing, so each way's files are found once
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])
        self.assertEqual([call.args[1] for call in pick_files.call_args_list], [['x', 'y', 'z']] * 2)

    def test_the_pair_can_be_made_a_favorite_and_not(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        known = replicas.Replicas()
        answers = ['Add to favorites', 'Remove from favorites', 'Quit']
        menus, saved = [], []
        def pick_option(options, **_):
            menus.append(options[-2:])
            return answers.pop(0)
        with mock.patch('dirdelta.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.replicas.save',
                           side_effect=lambda known: saved.append(list(known.favorites))):
            dirsync_main._sync(a, b, '/a', '/b', known)
        self.assertEqual(menus, [['Add to favorites', 'Quit'], ['Remove from favorites', 'Quit'],
                                 ['Add to favorites', 'Quit']])
        self.assertEqual(saved, [[('/a', '/b')], []])

    def test_run_records_the_pair(self):
        known = replicas.Replicas()
        args = mock.Mock(dir_a_path='/a', dir_b_path='/b', max_depth=None)
        with mock.patch('dirdelta.utils.validate_dir'), \
                mock.patch('dirdelta.replicas.load', return_value=known), \
                mock.patch('dirdelta.replicas.save') as save, \
                mock.patch('dirdelta.dirsync_main._sync') as sync:
            dirsync_main.run(args)
        self.assertEqual(known.history, [('/a', '/b')])
        save.assert_called_once_with(known)
        self.assertIs(sync.call_args.args[4], known)

    def test_a_live_action_finds_the_files_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Copy files from /a to /b', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.picker.pick_files', return_value=None), \
                mock.patch('dirdelta.dryrun.DRYRUN', False):
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])
