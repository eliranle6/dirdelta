"""Reading the replicas anew: from Drive, and the local ones"""
import unittest
from unittest import mock

import helpers
from dirdelta.drive import clouddirtree
from dirdelta.hashes import hashing
from dirdelta.trees import dirtree
from dirdelta.ui import messages
from dirdelta.ui import picker
from sync_way_support import NOTHING, Sync, TwoDirsTestCase


class RefreshKeyTest(unittest.TestCase):
    """The file picker's key that reads the selected folder anew from Drive"""
    def setUp(self):
        self.cloud = clouddirtree.CloudDirTree('cloud/mein')
        for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
            self.cloud.add_file_by_relpath(relpath)
        self.local = dirtree.DirTree('/local')
        for patcher in (mock.patch('dirdelta.ui.messages.show'),
                        mock.patch('dirdelta.ui.picker.pick_option', return_value=NOTHING)):
            self.addCleanup(patcher.stop)
            patcher.start()
        self.show = messages.show

    def browse(self, src, dst, answers, refresh=None):
        """Browse, the file picker answering answers in turn; returns pick_files's calls"""
        with mock.patch('dirdelta.ui.picker.pick_files', side_effect=answers) as pick_files, \
                mock.patch.object(clouddirtree.CloudDirTree, 'refresh_from_drive', autospec=True,
                                  side_effect=refresh) as self.refresh:
            self.sync = Sync(src, dst, checked={'a/1.mp3': {'x': True}})
            self.sync.src_index.build()
            self.sync.browse()
        return pick_files.call_args_list

    def test_the_key_refreshes_the_selected_folder_and_picks_again_where_it_was(self):
        def refresh(tree, relpath):
            # Since the cache was made, a/2.mp3 went from Drive
            tree.remove_node('a/2.mp3')
        calls = self.browse(self.cloud, self.local,
                            [picker.Picked(Sync.REFRESH_KEY, 'a', ['a/1.mp3', 'a/2.mp3']), None], refresh)
        self.refresh.assert_called_once_with(self.cloud, 'a')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(self.sync.checked, {})
        # Its files by name are listed again, when they're next needed
        self.assertFalse(self.sync.src_index.is_built())
        # And the replicas dashboard's
        self.assertEqual(calls[0].kwargs['keys'], Sync.REFRESH_KEY + '#a:e')
        self.assertIn("  %-17s%s" % ('Ctrl-R', 'read the folder anew from Drive'), calls[0].kwargs['help_lines'])
        self.assertIsNone(calls[0].kwargs['selected'])
        # What's still missing, what's still picked of it, where it was
        self.assertEqual(calls[1].args[1], ['a/1.mp3', 'b/3.mp3'])
        self.assertEqual(calls[1].kwargs['picked'], ['a/1.mp3'])
        self.assertEqual(calls[1].kwargs['selected'], 'a')

    def test_read_anew_in_the_menu_refreshes_the_selected_files_folder(self):
        with helpers.answering_option_picker(['Read cloud/mein/a/ anew from Google Drive']) as pick_option:
            calls = self.browse(self.cloud, self.local,
                                [picker.Picked('', 'a/2.mp3', ['a/1.mp3']), None])
        self.refresh.assert_called_once_with(self.cloud, 'a/2.mp3')
        self.assertEqual(helpers.labels_of(pick_option.call_args.args[0])[-1], 'Read cloud/mein/a/ anew from Google Drive')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(calls[1].kwargs['picked'], ['a/1.mp3'])
        self.assertEqual(calls[1].kwargs['selected'], 'a/2.mp3')

    def test_the_other_replica_is_refreshed_when_its_drives(self):
        self.local.add_file_by_relpath('x/new.mp3')
        self.browse(self.local, self.cloud, [picker.Picked(Sync.REFRESH_KEY, 'x/new.mp3', []), None])
        self.refresh.assert_called_once_with(self.cloud, 'x/new.mp3')

    def test_the_side_tree_is_listed_anew_and_is_gone_back_to_after_the_key_there(self):
        other = dirtree.DirTree('/other')
        other.add_file_by_relpath('a.mp3')
        with mock.patch('dirdelta.ui.sidetree._listed', return_value=([], [], None)) as listed:
            calls = self.browse(other, self.local, [picker.Picked(Sync.REFRESH_KEY, 'a.mp3', ['a.mp3']),
                                                    picker.Picked(picker.SIDE_KEY, 'a.mp3', ['a.mp3'], 'x', Sync.REFRESH_KEY),
                                                    picker.Picked('', 'a.mp3', ['a.mp3']), None])
        # Once to start with, once for each Ctrl-R, not for another return to the picker
        self.assertEqual(listed.call_count, 3)
        self.assertEqual(len(calls), 4)
        self.refresh.assert_not_called()
        self.assertEqual(calls[0].kwargs['keys'], Sync.REFRESH_KEY + '#a:e')
        self.assertIn(Sync.REFRESH_KEY, calls[0].kwargs['side'].keys)
        self.assertEqual(calls[1].kwargs['picked'], ['a.mp3'])
        # After the key in the side tree, it's where the picker starts; only then
        self.assertEqual([call.kwargs['side'].start for call in calls], [None, None, 'x', None])

    def test_the_key_in_the_side_tree_reads_whats_selected_there_only_in_dst(self):
        self.local.add_file_by_relpath('x/new.mp3')
        calls = self.browse(self.local, self.cloud,
                            [picker.Picked(picker.SIDE_KEY, 'x/new.mp3', [], 'b', Sync.REFRESH_KEY), None])
        self.refresh.assert_called_once_with(self.cloud, 'b')
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.sync.has_changed)

    def test_a_refresh_with_nothing_left_missing_says_so(self):
        def refresh(tree, relpath):
            for relpath in ('a/1.mp3', 'a/2.mp3', 'b/3.mp3'):
                tree.remove_node(relpath)
        calls = self.browse(self.cloud, self.local, [picker.Picked(Sync.REFRESH_KEY, '', [])], refresh)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.show.call_args.args[0], 'Nothing to do')

    def test_a_failed_refresh_says_why_and_picks_again(self):
        calls = self.browse(self.cloud, self.local,
                            [picker.Picked(Sync.REFRESH_KEY, 'a', ['b/3.mp3']), None], OSError('no network'))
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'Refresh cloud/mein/a from Google Drive')
        self.assertEqual(lines, ["Couldn't refresh it: no network"])
        self.assertFalse(self.sync.has_changed)
        self.assertEqual(calls[1].kwargs['picked'], ['b/3.mp3'])


class ReadingLocalReplicasAnewTest(TwoDirsTestCase):
    """Ctrl-R, for what changed outside dirdelta"""

    def press(self, chosen):
        """browse(), the key pressed as chosen says after dst got a.txt from outside dirdelta; returns
        pick_files's calls"""
        answers = [chosen, None]

        def pick_files(root, items, **kwargs):
            answer = answers.pop(0)
            if answer is not None:
                helpers.make_files(self.dst_path, ['a.txt'])
            return answer
        self.sync.src_index.build()
        self.sync.dst_index.build()
        self.sync.checked['a.txt'] = {'x': True}
        with mock.patch('dirdelta.ui.picker.pick_files', side_effect=pick_files) as called:
            self.sync.browse()
        return called.call_args_list

    def test_what_each_lacks_is_found_anew(self):
        calls = self.press(picker.Picked(Sync.REFRESH_KEY, 'b.txt', ['a.txt', 'b.txt']))
        self.assertEqual(sorted(calls[1].args[1]), ['b.txt', 'c.txt'])
        self.assertEqual(calls[1].kwargs['picked'], ['b.txt'])
        self.assertEqual(calls[1].kwargs['selected'], 'b.txt')
        self.assertTrue(self.sync.has_changed)
        self.assertEqual(self.sync.checked, {})
        self.assertFalse(self.sync.src_index.is_built())
        self.assertFalse(self.sync.dst_index.is_built())
        self.assertIn('f a.txt', calls[1].kwargs['side'].items)

    def test_dsts_hashing_gets_the_side_trees_listing_and_srcs_lists_its_own(self):
        src_job, dst_job = hashing.Job(self.src_path), hashing.Job(self.dst_path)
        with mock.patch('dirdelta.hashes.hashing.registry._jobs', {self.src_path: src_job, self.dst_path: dst_job}), \
                mock.patch.object(hashing.Job, 'scan'), \
                mock.patch.object(src_job, 'scan_in_background') as src_scan, \
                mock.patch.object(dst_job, 'scan_in_background') as dst_scan:
            self.press(picker.Picked(Sync.REFRESH_KEY, 'b.txt', []))
        src_scan.assert_called_once_with()
        dst_scan.assert_called_once()
        self.assertIn('a.txt', dst_scan.call_args.args[0])

    def test_in_the_side_tree_only_dst_is_and_it_stays_there(self):
        calls = self.press(picker.Picked(picker.SIDE_KEY, 'b.txt', [], 'old/d.txt', Sync.REFRESH_KEY))
        self.assertEqual(sorted(calls[1].args[1]), ['b.txt', 'c.txt'])
        self.assertTrue(self.sync.src_index.is_built())
        self.assertFalse(self.sync.dst_index.is_built())
        self.assertEqual(calls[1].kwargs['side'].start, 'old/d.txt')


if __name__ == '__main__':
    unittest.main()
