import concurrent.futures
import time
import unittest
from unittest import mock

from dirdelta import clouddirtree
from dirdelta import dirsync_main
from dirdelta import dirtree
from dirdelta import elsewhere
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
        for patcher in (mock.patch('dirdelta.interactive_dir_sync.os.access',
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

    def test_each_way_gets_its_files(self):
        for b in (localdiskdirtree.LocalDiskDirTree('/b', silent=True), dirtree.DirTree('cloud/b')):
            a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
            self.assertEqual(self.options(a, b), ['Files in /a, not in /b', 'Files in /b, not in /a', 'Quit'])

    def test_a_cloud_replica_can_be_refreshed_from_drive(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        self.assertEqual(self.options(a, b)[-2:], ['Refresh /b from Google Drive', 'Quit'])

    def test_a_refresh_finds_each_ways_files_again_and_lists_its_files_anew(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        answers = ['Refresh /b from Google Drive', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(b, 'refresh_from_drive') as refresh, \
                mock.patch.object(elsewhere.Index, 'invalidate', autospec=True) as invalidate:
            dirsync_main._sync(a, b, '/a', '/b')
        refresh.assert_called_once_with('')
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])
        self.assertEqual([call.args[0].replica for call in invalidate.call_args_list], [b])

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

    def browse(self, answers, has_changed=False):
        """The main menu answering answers in turn, each way's browse() changing the replicas'
        files if has_changed; returns the syncs browsed"""
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        syncs = []

        def browse(sync):
            syncs.append(sync)
            sync.has_changed = has_changed
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.interactive_dir_sync.InteractiveDirSync.browse', autospec=True,
                           side_effect=browse):
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(answers, [])
        return syncs

    def test_the_chosen_way_is_browsed_and_the_menu_comes_back(self):
        syncs = self.browse(['Files in /b, not in /a', 'Quit'])
        self.assertEqual(len(syncs), 1)
        self.assertEqual(syncs[0]._src.fullpath(), '/b')
        # A dry run changes nothing, so each way's files are found once
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])

    def test_each_replicas_files_by_name_are_kept_between_ways(self):
        syncs = self.browse(['Files in /a, not in /b', 'Files in /b, not in /a', 'Quit'])
        self.assertIs(syncs[0].dst_index, syncs[1].src_index)
        self.assertIs(syncs[0].src_index, syncs[1].dst_index)
        self.assertEqual(syncs[0].dst_index.replica.fullpath(), '/b')

    def test_a_change_while_browsing_finds_each_ways_files_again(self):
        # E.g. a live action, or a refresh in the file picker
        self.browse(['Files in /a, not in /b', 'Quit'], has_changed=True)
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])

    def test_read_only_replicas_are_said_to_be_before_the_menu(self):
        self.writable = set()
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        self.assertEqual(self.options(a, b), ['Files in /a, not in /b', 'Files in /b, not in /a', 'Quit'])
        title, lines, _ = self.show.call_args.args
        self.assertEqual(title, 'Read-only')
        self.assertEqual(len(lines), 1)
        self.assertIn('/a is read-only', lines[0])

    def test_writable_replicas_get_no_read_only_message(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.options(a, b)
        self.show.assert_not_called()

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
            'Files in /a, not in /b (3 files)',
            'Files in /b, not in /a (1 file)',
            'Quit',
        ])

    def test_a_way_with_no_files_cant_be_picked(self):
        self.missing['/b'] = []
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b)[1],
                         picker.Disabled('Files in /b, not in /a: none, /a has them all'))

    def test_options_are_loading_until_their_files_are_found(self):
        way = dirsync_main._Way(None, None, {})
        way.missing = concurrent.futures.Future()
        action = dirsync_main._Action('Files', way, 'none')
        shown = set()
        for now in (0, 0.4, 0.8, 1.2, 1.6):
            with mock.patch('dirdelta.dirsync_main.time.monotonic', return_value=now + 0.1):
                shown.add(action.shown_as())
        self.assertEqual(shown, {'Files (loading)', 'Files (loading.)', 'Files (loading..)',
                                 'Files (loading...)'})
        way.missing.set_result(interactive_dir_sync.Missing(['x', 'y'], []))
        self.assertEqual(action.shown_as(), 'Files (2 files)')

    def test_an_option_whose_files_couldnt_be_found_says_so(self):
        way = dirsync_main._Way(None, None, {})
        way.missing = concurrent.futures.Future()
        way.missing.set_exception(RuntimeError('dirdiff failed'))
        action = dirsync_main._Action('Files', way, 'none')
        self.assertEqual(action.shown_as(), "Files (couldn't count the files)")

    def test_browsing_uses_the_files_found_in_the_background(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Files in /a, not in /b', 'Files in /a, not in /b', 'Quit']
        with mock.patch('dirdelta.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.picker.pick_files', return_value=None) as pick_files:
            dirsync_main._sync(a, b, '/a', '/b')
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
