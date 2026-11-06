"""What the sync menu's options do: browsing a way, refreshing and rescanning the replicas"""
import unittest
from unittest import mock

from dirdelta.drive import clouddirtree
from dirdelta.matching import differing
from dirdelta.matching import elsewhere
from dirdelta.sync import dirsync_main
from dirdelta.sync import ways
from dirdelta.sync.way import interactive_dir_sync
from dirdelta.trees import localdiskdirtree
from sync_menu_support import MainMenuTest


class ActionsTest(MainMenuTest):
    """The options done"""

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

    def test_the_files_that_differ_option_browses_them_alone_from_as_side(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        self.differ = {'d1': differing.Change(1, 2, None, None, differing.BY_SIZE)}
        answers = [ways.DIFFER, dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.ui.picker.pick_files', return_value=None) as pick_files:
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual([call.args[1] for call in pick_files.call_args_list], [['d1']])
        self.assertIn('other versions', pick_files.call_args.kwargs['header'])

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
                mock.patch.object(interactive_dir_sync.InteractiveDirSync, 'browse', autospec=True, side_effect=browse):
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
                mock.patch.object(interactive_dir_sync.InteractiveDirSync, 'browse', autospec=True, side_effect=browse):
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

    def test_browsing_uses_the_files_found_in_the_background(self):
        a = localdiskdirtree.LocalDiskDirTree('/a', silent=True)
        b = localdiskdirtree.LocalDiskDirTree('/b', silent=True)
        answers = ['Files only in /a', 'Files only in /a', dirsync_main.BACK]
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda *_, **__: answers.pop(0)), \
                mock.patch('dirdelta.ui.picker.pick_files', return_value=None) as pick_files:
            dirsync_main._sync(a, b, '/a', '/b')
        self.assertEqual(sorted(self.find_missing_calls), ['/a', '/b'])
        self.assertEqual([call.args[1] for call in pick_files.call_args_list], [['x', 'y', 'z']] * 2)


if __name__ == '__main__':
    unittest.main()
