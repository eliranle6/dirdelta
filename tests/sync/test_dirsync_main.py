"""The sync menu: its options, their counts, and its first line"""
import concurrent.futures
import time
import unittest
from unittest import mock

from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashing
from dirdelta.known import replicas
from dirdelta.matching import differing
from dirdelta.sync import comparing
from dirdelta.sync import dirsync_main
from dirdelta.sync import options as menu_options
from dirdelta.sync import replica_ops
from dirdelta.sync import ways
from dirdelta.trees import dirtree
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import picker
from sync_menu_support import MainMenuTest


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


class OptionsTest(MainMenuTest):
    """What the menu offers, and says"""

    def test_each_way_gets_its_files(self):
        for b, rescans in ((localdiskdirtree.LocalDiskDirTree('/b', silent=True), ['Rescan /a', 'Rescan /b']),
                           (dirtree.DirTree('cloud/b'), ['Rescan /a'])):
            a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
            self.assertEqual(self.options(a, b), ['Files only in /a', 'Files only in /b', ways.DIFFER, comparing.COMPARE] + rescans +
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
        with mock.patch('dirdelta.hashes.hashing.registry._jobs', {'/a': job}), \
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

    def test_read_only_replicas_are_said_to_be_before_the_menu(self):
        self.writable = set()
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = dirtree.DirTree('cloud/b')
        self.assertEqual(self.options(a, b), ['Files only in /a', 'Files only in /b', ways.DIFFER, comparing.COMPARE, 'Rescan /a',
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
            picker.Disabled('Compare the files of the same size at the same paths in both: none not compared'),
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
        way = ways.Way(None, None, {})
        way.missing = concurrent.futures.Future()
        way.missing.set_result(replica_ops.Missing([], []))
        way.differs = concurrent.futures.Future()
        action = menu_options.Action('/a', '/b', way, only_differing=True)
        self.assertIn('(loading', action.shown_as())
        way.differs.set_exception(OSError('no'))
        self.assertEqual(action.shown_as(), "Files that differ at the same paths in both (couldn't compare them)")

    def test_an_option_whose_files_couldnt_be_found_says_so(self):
        way = ways.Way(None, None, {})
        way.missing = concurrent.futures.Future()
        way.missing.set_exception(RuntimeError('dirdiff failed'))
        action = menu_options.Action('/a', '/b', way)
        self.assertEqual(action.shown_as(), "Files only in LocalDisk:/a (couldn't count the files)")

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


if __name__ == '__main__':
    unittest.main()
