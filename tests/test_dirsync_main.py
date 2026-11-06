import concurrent.futures
import time
import unittest
from unittest import mock

from dirdelta.drive import clouddirtree
from dirdelta.matching import differing
from dirdelta.sync import dirsync_main
from dirdelta.ui import picker
from dirdelta.trees import dirtree
from dirdelta.matching import elsewhere
from dirdelta.hashes import hashing
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.sync import replica_ops


class ScanErrorsWarningTest(unittest.TestCase):
    def warning(self, scan_errors):
        tree = dirtree.DirTree('/some/dir')
        tree.scan_errors = scan_errors
        return replica_ops.scan_errors_warning(tree)

    def test_trees_without_scan_errors_get_no_warning(self):
        # E.g. cloud trees, which aren't scanned with find
        self.assertEqual(replica_ops.scan_errors_warning(dirtree.DirTree('cloud/mein')), [])

    def test_errors_are_listed(self):
        self.assertEqual(self.warning(["find: '/some/dir/a': Permission denied"]), [
            "Couldn't read everything in /some/dir (1 error), so the diff may be wrong:",
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
        patcher = mock.patch('dirdelta.matching.differing.find', side_effect=lambda src, dst: dict(self.differ))
        patcher.start()
        self.addCleanup(patcher.stop)

    def shown(self, replica_a, replica_b):
        """What the main menu's options are shown as, once each way's files are found"""
        def pick_option(options, shown_as, **_):
            while any('loading' in shown for shown in shown_as().values()):
                time.sleep(0.01)
            self.shown_options = [shown_as().get(option, option) for option in options[2:]]
            self.state_line = shown_as()[dirsync_main.STATE]
            return dirsync_main.BACK
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option):
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        return self.shown_options

    def options(self, replica_a, replica_b):
        with mock.patch('dirdelta.ui.picker.pick_option', return_value=dirsync_main.BACK) as pick_option:
            dirsync_main._sync(replica_a, replica_b, '/a', '/b')
        options, = pick_option.call_args.args
        self.assertEqual(options[:2], [picker.Option(dirsync_main.STATE, dirsync_main.STATE, picker.Skipped(dirsync_main.STATE)),
                                       picker.BLANK])
        return options[2:]

    def test_each_way_gets_its_files(self):
        for b, rescans in ((localdiskdirtree.LocalDiskDirTree('/b', silent=True), ['Rescan /a', 'Rescan /b']),
                           (dirtree.DirTree('cloud/b'), ['Rescan /a'])):
            a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
            self.assertEqual(self.options(a, b), ['Files only in /a', 'Files only in /b', dirsync_main.DIFFER] + rescans +
                             ['Replicas dashboard', dirsync_main.BACK])

    def test_back_and_q_go_back_to_the_start_menu(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        for answer in (dirsync_main.BACK, None):
            with mock.patch('dirdelta.ui.picker.pick_option', return_value=answer):
                self.assertIsNone(dirsync_main._sync(a, b, '/a', '/b'))

    def test_a_hashed_replicas_hashes_are_an_option_and_on_the_bottom_line(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        job = hashing.Job('/a')
        answers = ['Replicas dashboard', dirsync_main.BACK]
        shown = []

        def pick_option(options, shown_as, **_):
            shown.append(shown_as())
            return answers.pop(0)
        with mock.patch('dirdelta.hashes.hashing._jobs', {'/a': job}), \
                mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.screens.hashes_screen.dashboard') as dashboard:
            dirsync_main._sync(a, b, '/a', '/b')
        dashboard.assert_called_once_with([a, b], None)
        self.assertEqual(shown[0]['Replicas dashboard'],
                         "Replicas dashboard: files, last updates, hashes (a: listing its files...)")
        self.assertIn("a: listing its files...", shown[0][''])

    def test_a_cloud_replica_can_be_refreshed_from_drive(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        self.assertEqual(self.options(a, b)[-3:], ['Refresh /b file list from Google Drive', 'Replicas dashboard', dirsync_main.BACK])

    def test_a_refresh_finds_each_ways_files_again_and_lists_its_files_anew(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        answers = ['Refresh /b file list from Google Drive', dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(b, 'refresh_from_drive') as refresh, \
                mock.patch.object(elsewhere.Index, 'invalidate', autospec=True) as invalidate:
            dirsync_main._sync(a, b, '/a', '/b')
        refresh.assert_called_once_with('')
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])
        self.assertEqual([call.args[0].replica for call in invalidate.call_args_list], [b])

    def test_a_failed_refresh_says_why_and_finds_nothing_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = clouddirtree.CloudDirTree('cloud/b')
        answers = ['Refresh /b file list from Google Drive', dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
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
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.sync.interactive_dir_sync.InteractiveDirSync.browse', autospec=True,
                           side_effect=browse):
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(answers, [])
        return syncs

    def test_the_chosen_way_is_browsed_and_the_menu_comes_back(self):
        syncs = self.browse(['Files only in /b', dirsync_main.BACK])
        self.assertEqual(len(syncs), 1)
        self.assertEqual(syncs[0]._src.fullpath(), '/b')
        # A dry run changes nothing, so each way's files are found once
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])

    def test_each_replicas_files_by_name_are_kept_between_ways(self):
        syncs = self.browse(['Files only in /a', 'Files only in /b', dirsync_main.BACK])
        self.assertIs(syncs[0].dst_index, syncs[1].src_index)
        self.assertIs(syncs[0].src_index, syncs[1].dst_index)
        self.assertEqual(syncs[0].dst_index.replica.fullpath(), '/b')

    def test_a_change_while_browsing_finds_each_ways_files_again(self):
        # E.g. a live action, or a refresh in the file picker
        self.browse(['Files only in /a', dirsync_main.BACK], has_changed=True)
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/a', '/b', '/b'])

    def test_read_only_replicas_are_said_to_be_before_the_menu(self):
        self.writable = set()
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        self.assertEqual(self.options(a, b), ['Files only in /a', 'Files only in /b', dirsync_main.DIFFER, 'Rescan /a',
                                              'Replicas dashboard', dirsync_main.BACK])
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Read-only')
        self.assertEqual(len(lines), 1)
        self.assertIn('/a is read-only', lines[0])
        self.assertIn('you can still copy', lines[0])

    def test_writable_replicas_get_no_read_only_message(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.options(a, b)
        self.show.assert_not_called()

    def test_options_say_how_many_files_they_are_about(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b), [
            'Files only in LocalDisk:/a (3 files)',
            'Files only in LocalDisk:/b (1 file)',
            picker.Disabled('Files that differ at the same paths in both: none'),
            'Rescan /a',
            'Rescan /b',
            'Replicas dashboard: files, last updates, hashes',
            dirsync_main.BACK,
        ])

    def test_the_files_that_differ_are_counted_in_each_way_and_on_their_own(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.differ = {'d1': differing.Change(1, 2, None, None, differing.BY_SIZE),
                       'd2': differing.Change(3, 3, None, None, differing.BY_CONTENTS)}
        self.assertEqual(self.shown(a, b)[:3], [
            'Files only in LocalDisk:/a (3 files, and 2 that differ)',
            'Files only in LocalDisk:/b (1 file, and 2 that differ)',
            'Files that differ at the same paths in both (2 files)',
        ])
        self.assertTrue(picker.unstyled(self.state_line.text).endswith("; 2 files at the same paths differ"))

    def test_a_way_with_only_files_that_differ_can_still_be_picked(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.missing['/b'] = []
        self.differ = {'d1': differing.Change(1, 2, None, None, differing.BY_SIZE)}
        self.assertEqual(self.shown(a, b)[1], 'Files only in LocalDisk:/b (0 files, and 1 that differs)')

    def test_the_files_that_differ_option_browses_them_alone_from_as_side(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.differ = {'d1': differing.Change(1, 2, None, None, differing.BY_SIZE)}
        answers = [dirsync_main.DIFFER, dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.ui.picker.pick_files', return_value=None) as pick_files:
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual([call.args[1] for call in pick_files.call_args_list], [['d1']])
        self.assertIn('other versions', pick_files.call_args.kwargs['header'])

    def test_the_first_line_says_whether_theyre_in_sync(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.shown(a, b)
        self.assertIsInstance(self.state_line, picker.Skipped)
        self.assertEqual(picker.unstyled(self.state_line.text),
                         "\u2260 Branched: a has 3 files that b lacks, and b has 1 file that a lacks")
        self.missing['/b'] = []
        self.shown(a, b)
        self.assertIn("a is ahead: it has 3 files that b lacks", picker.unstyled(self.state_line.text))

    def test_rescanning_finds_each_ways_files_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Rescan /b', dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(localdiskdirtree.LocalDiskDirTree, 'rescan') as rescan, \
                mock.patch('dirdelta.matching.elsewhere.Index.invalidate', autospec=True) as invalidate:
            calls_before = len(self.find_missing_calls)
            dirsync_main._sync(a, b, '/a', '/b')
        rescan.assert_called_once_with()
        self.assertIs(invalidate.call_args.args[0].replica, b)
        # Each way, at first and again
        self.assertGreaterEqual(len(self.find_missing_calls) - calls_before, 2)

    def test_reading_anew_in_one_way_forgets_the_other_ways_comparisons_too(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Files only in /a', 'Files only in /b', dirsync_main.BACK]
        checked = []

        def browse(sync):
            checked.append(sync.checked)
            if len(checked) == 1:
                sync.checked['x'] = {'y': True}
            else:
                sync.has_changed = sync.was_read_anew = True
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(dirsync_main.interactive_dir_sync.InteractiveDirSync, 'browse', autospec=True, side_effect=browse):
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(checked[0], {})

    def test_a_copy_keeps_the_ways_comparisons(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Files only in /a', dirsync_main.BACK]
        checked = []

        def browse(sync):
            checked.append(sync.checked)
            sync.checked['x'] = {'y': True}
            sync.has_changed = True
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(dirsync_main.interactive_dir_sync.InteractiveDirSync, 'browse', autospec=True, side_effect=browse):
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(checked[0], {'x': {'y': True}})

    def test_a_rescan_that_fails_says_so_and_finds_nothing_again(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Rescan /b', dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch.object(localdiskdirtree.LocalDiskDirTree, 'rescan', side_effect=OSError('/b is gone')), \
                mock.patch('dirdelta.matching.elsewhere.Index.invalidate', autospec=True) as invalidate:
            dirsync_main._sync(a, b, '/a', '/b')
        invalidate.assert_not_called()
        self.assertEqual(self.show.call_args.args[0], "Couldn't rescan it")

    def test_what_was_found_is_noted_for_the_start_menu(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        known = replicas.Replicas()

        def pick_option(options, shown_as, **_):
            while any('loading' in str(shown) for shown in shown_as().values()):
                time.sleep(0.01)
            return None
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option), mock.patch('dirdelta.known.replicas.save'):
            dirsync_main._sync(a, b, '/a', '/b', known)
        self.assertEqual(known.comparison('/b', '/a')['only'], [1, 3])

    def test_a_way_with_no_files_cant_be_picked(self):
        self.missing['/b'] = []
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.assertEqual(self.shown(a, b)[1],
                         picker.Disabled('Files only in LocalDisk:/b: none, LocalDisk:/a has them all'))

    def test_the_files_that_differ_option_is_loading_until_theyre_found(self):
        way = dirsync_main._Way(None, None, {})
        way.missing = concurrent.futures.Future()
        way.missing.set_result(replica_ops.Missing([], []))
        way.differs = concurrent.futures.Future()
        action = dirsync_main._Action('/a', '/b', way, only_differing=True)
        self.assertIn('(loading', action.shown_as())
        way.differs.set_exception(OSError('no'))
        self.assertEqual(action.shown_as(), "Files that differ at the same paths in both (couldn't compare them)")

    def test_an_option_whose_files_couldnt_be_found_says_so(self):
        way = dirsync_main._Way(None, None, {})
        way.missing = concurrent.futures.Future()
        way.missing.set_exception(RuntimeError('dirdiff failed'))
        action = dirsync_main._Action('/a', '/b', way)
        self.assertEqual(action.shown_as(), "Files only in LocalDisk:/a (couldn't count the files)")

    def test_browsing_uses_the_files_found_in_the_background(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Files only in /a', 'Files only in /a', dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.ui.picker.pick_files', return_value=None) as pick_files:
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])
        self.assertEqual([call.args[1] for call in pick_files.call_args_list], [['x', 'y', 'z']] * 2)

    def test_the_pair_can_be_made_a_favorite_and_not(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        known = replicas.Replicas()
        answers = ['Add to favorites', 'Remove from favorites', dirsync_main.BACK]
        menus, saved = [], []
        def pick_option(options, **_):
            menus.append(options[-3:-2] + options[-1:])
            return answers.pop(0)
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.known.replicas.save',
                           side_effect=lambda known: saved.append(list(known.favorites))):
            dirsync_main._sync(a, b, '/a', '/b', known)
        # (What the ways found is saved too, when they found it: only the favorites' changes here)
        saved = [favorites for number, favorites in enumerate(saved)
                 if favorites != (saved[number - 1] if number else [])]
        self.assertEqual(menus, [['Add to favorites', dirsync_main.BACK], ['Remove from favorites', dirsync_main.BACK],
                                 ['Add to favorites', dirsync_main.BACK]])
        self.assertEqual(saved, [[('/a', '/b')], []])

    def test_run_records_the_pair(self):
        known = replicas.Replicas()
        args = mock.Mock(dir_a_path='/a', dir_b_path='/b', max_depth=None)
        with mock.patch('dirdelta.trees.replicafactory.validate_dir'), \
                mock.patch('dirdelta.known.replicas.load', return_value=known), \
                mock.patch('dirdelta.known.replicas.save') as save, \
                mock.patch('dirdelta.sync.dirsync_main._sync') as sync:
            dirsync_main.run(args)
        self.assertEqual(known.history, [('/a', '/b')])
        save.assert_called_once_with(known)
        self.assertIs(sync.call_args.args[4], known)
