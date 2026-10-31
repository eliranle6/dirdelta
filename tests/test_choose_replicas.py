import datetime
import unittest
from unittest import mock

from dirdelta import choose_replicas
from dirdelta import dirtree
from dirdelta import drivecache
from dirdelta import replicalog
from dirdelta import replicas
import helpers

NONE = choose_replicas.NOT_CHOSEN
SORT = choose_replicas.SORT
SYNC_SECTION = choose_replicas.SYNC_SECTION
SORT_SECTION = choose_replicas.SORT_SECTION


class ChooseReplicasTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('dirdelta.messages.show')
        self.show = patcher.start()
        self.addCleanup(patcher.stop)
        self.known = replicas.Replicas()
        self.menus = []

    def run_menu(self, answers, dir_picks=(), tree_picks=()):
        """Run it, answering each menu with the next of answers, and each local and cloud dir pick
        with the next of dir_picks and tree_picks"""
        answers, dir_picks, tree_picks = list(answers), list(dir_picks), list(tree_picks)
        def pick_option(options, header='', **kwargs):
            self.menus.append(options)
            self.kwargs = kwargs
            return answers.pop(0)
        with mock.patch('dirdelta.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.picker.pick_under_dir',
                           side_effect=lambda *_, **__: dir_picks.pop(0)) as self.pick_under_dir, \
                mock.patch('dirdelta.picker.pick_from_tree',
                           side_effect=lambda *_, **__: tree_picks.pop(0)) as self.pick_from_tree:
            return choose_replicas.run(self.known)

    def test_the_slots_start_not_chosen(self):
        self.assertIsNone(self.run_menu(['Quit']))
        self.assertEqual(self.menus, [[SYNC_SECTION, '  Replica A: ' + NONE, '  Replica B: ' + NONE,
                                       SORT_SECTION, SORT, 'Quit']])

    def test_the_headings_cant_be_picked_and_the_first_slot_is_selected(self):
        self.run_menu(['Quit'])
        self.assertEqual(sorted(self.kwargs['shown_as']()),
                         sorted([SYNC_SECTION, choose_replicas.RECENT_SYNCS_SECTION, SORT_SECTION,
                                 choose_replicas.RECENT_SORTS_SECTION, choose_replicas.REPLICAS_SECTION]))
        self.assertTrue(all(isinstance(shown, choose_replicas.picker.Disabled)
                            for shown in self.kwargs['shown_as']().values()))
        self.assertEqual(self.kwargs['selected'], '  Replica A: ' + NONE)

    def test_two_local_dirs(self):
        chosen = self.run_menu(['  Replica A: ' + NONE, 'Local disk',
                                '  Replica B: ' + NONE, 'Local disk'],
                               dir_picks=['/mnt/win', '/home/me'])
        self.assertEqual(chosen, ('/mnt/win', '/home/me'))
        self.assertEqual(self.menus[2], [SYNC_SECTION, '  Replica A: /mnt/win', '  Replica B: ' + NONE,
                                         SORT_SECTION, SORT, 'Quit'])
        # Only dirs, under /, read as they're shown
        args, kwargs = self.pick_under_dir.call_args
        self.assertEqual(args, ('/',))
        self.assertTrue(kwargs['dirs_only'])
        self.assertTrue(kwargs['lazy'])

    def test_a_cloud_dir(self):
        tree = dirtree.DirTree('/')
        tree.add_file_by_relpath('me/music/song.mp3')
        music = tree.get_node('me/music').data
        with mock.patch('dirdelta.utils.create_dirtree_from_arg', return_value=tree) as create:
            chosen = self.run_menu(['  Replica B: ' + NONE, 'Google Drive',
                                    '  Replica A: ' + NONE, 'Local disk'],
                                   dir_picks=['/mnt/win'], tree_picks=[[music]])
        create.assert_called_once_with('cloud')
        self.assertEqual(chosen, ('/mnt/win', 'cloud/me/music'))
        self.assertTrue(self.pick_from_tree.call_args.kwargs['dirs_only'])

    def test_nothing_at_the_refresh_question_is_back_to_the_menu(self):
        with mock.patch('dirdelta.utils.create_dirtree_from_arg', return_value=None):
            self.assertIsNone(self.run_menu(['  Replica A: ' + NONE, choose_replicas.CLOUD, 'Quit']))
        self.pick_from_tree.assert_not_called()
        self.assertEqual(len(self.menus), 3)

    def test_drives_top_is_cloud(self):
        tree = dirtree.DirTree('/')
        with mock.patch('dirdelta.utils.create_dirtree_from_arg', return_value=tree):
            chosen = self.run_menu(['  Replica A: ' + NONE, 'Google Drive',
                                    '  Replica B: ' + NONE, 'Local disk'],
                                   dir_picks=['/a'], tree_picks=[[tree.get_node('').data]])
        self.assertEqual(chosen, ('cloud', '/a'))

    def test_a_drive_cache_error_is_shown(self):
        with mock.patch('dirdelta.utils.create_dirtree_from_arg',
                        side_effect=drivecache.DriveCacheError('two folders named x')):
            self.assertIsNone(self.run_menu(['  Replica A: ' + NONE, 'Google Drive', 'Quit']))
        self.assertEqual(self.show.call_args.args[1], ['two folders named x'])

    def test_quitting_a_pick_keeps_the_slot(self):
        self.run_menu(['  Replica A: ' + NONE, 'Local disk', '  Replica A: ' + NONE, None, 'Quit'],
                      dir_picks=[None])
        self.assertEqual(self.menus[-1][1], '  Replica A: ' + NONE)

    def test_a_slot_can_be_chosen_again(self):
        chosen = self.run_menu(['  Replica A: ' + NONE, 'Local disk', '  Replica A: /x', 'Local disk',
                                '  Replica B: ' + NONE, 'Local disk'],
                               dir_picks=['/x', '/y', '/z'])
        self.assertEqual(chosen, ('/y', '/z'))

    def test_the_same_dir_twice_is_refused(self):
        self.run_menu(['  Replica A: ' + NONE, 'Local disk', '  Replica B: ' + NONE, 'Local disk',
                       'Quit'], dir_picks=['/x', '/x'])
        self.assertEqual(self.show.call_args.args[0], 'Same replica')
        self.assertEqual(self.menus[-1][1:3], ['  Replica A: /x', '  Replica B: ' + NONE])

    def test_favorites_then_recent_pairs(self):
        self.known.record('/a', '/b')
        self.known.record('/mnt/win', 'cloud/me')
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        self.known.toggle_favorite('/f', '/g')
        self.known.record('/c', '/d')
        with mock.patch('os.path.isdir', return_value=True):
            chosen = self.run_menu(['  /a <-> /b'])
        self.assertEqual(chosen, ('/a', '/b'))
        self.assertEqual(self.menus[0][3:], [
            '  Favorite: /mnt/win <-> cloud/me',
            '  Favorite: /f <-> /g',
            choose_replicas.RECENT_SYNCS_SECTION,
            # Not the favorite again
            '  /c <-> /d',
            '  /a <-> /b',
            SORT_SECTION,
            SORT,
            'Quit',
        ])

    def test_an_inbox_to_sort_and_its_sorted_tree(self):
        chosen = self.run_menu([SORT, 'Local disk', 'Local disk'], dir_picks=['/in', '/sorted'])
        self.assertEqual(chosen, choose_replicas.Sort('/in', '/sorted'))

    def test_the_sorted_tree_can_be_a_known_replica(self):
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        self.known.record('/home/me', 'cloud/me')
        self.known.record_sort('/in', 'cloud/sorted')
        chosen = self.run_menu([SORT, 'Local disk', 'Known replica: cloud/me'], dir_picks=['/home/me'])
        self.assertEqual(chosen, choose_replicas.Sort('/home/me', 'cloud/me'))
        # Each once, not the inbox just chosen; the dirs can still be picked anew
        self.assertEqual(self.menus[2], ['Known replica: /mnt/win', 'Known replica: cloud/me',
                                         'Known replica: cloud/sorted', 'Local disk', 'Google Drive'])
        # The inbox's own choice has no known ones
        self.assertEqual(self.menus[1], ['Local disk', 'Google Drive'])

    def test_quitting_a_sorts_pick_goes_back_to_the_menu(self):
        self.assertIsNone(self.run_menu([SORT, 'Local disk', 'Quit'], dir_picks=[None]))
        self.assertEqual(len(self.menus), 3)

    def test_recent_sorts_are_offered(self):
        self.known.record_sort('cloud/unsorted', 'cloud/me')
        chosen = self.run_menu(['  cloud/unsorted -> cloud/me'])
        self.assertEqual(self.menus[0][-3:], [choose_replicas.RECENT_SORTS_SECTION, '  cloud/unsorted -> cloud/me',
                                              'Quit'])
        self.assertEqual(chosen, choose_replicas.Sort('cloud/unsorted', 'cloud/me'))

    def test_a_favorite_is_chosen_at_once(self):
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        with mock.patch('os.path.isdir', return_value=True):
            chosen = self.run_menu(['  Favorite: /mnt/win <-> cloud/me'])
        self.assertEqual(chosen, ('/mnt/win', 'cloud/me'))

    def test_a_pair_whose_local_dir_is_gone_is_refused(self):
        self.known.record('/no/such/dir', 'cloud/me')
        self.assertIsNone(self.run_menu(['  /no/such/dir <-> cloud/me', 'Quit']))
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'No such directory')
        self.assertEqual(lines, ['/no/such/dir is not a directory (anymore?).'])
        # Back to the menu
        self.assertEqual(len(self.menus), 2)

    def test_a_pair_on_a_volume_not_mounted_is_back_to_the_menu_unless_its_mounted(self):
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        mounted = [False, True]
        asked = []

        def ensure_mounted(path):
            asked.append(path)
            return mounted.pop(0) if path == '/mnt/win' else True
        with mock.patch('dirdelta.mounts.ensure_mounted', side_effect=ensure_mounted), \
                mock.patch('os.path.isdir', return_value=True):
            chosen = self.run_menu(['  Favorite: /mnt/win <-> cloud/me'] * 2)
        self.assertEqual(chosen, ('/mnt/win', 'cloud/me'))
        self.assertEqual(len(self.menus), 2)
        # Going back from the first, the second isn't asked about
        self.assertEqual(asked, ['/mnt/win', '/mnt/win', 'cloud/me'])


    def test_pairs_say_when_each_replica_was_last_updated(self):
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        self.known.note_seen('uuid:U:/', '/mnt/win', replicalog.Entry(datetime.date(2026, 5, 17), 'removed x'),
                             datetime.datetime(2026, 10, 30, 9, 0))
        with mock.patch('os.path.isdir', return_value=True):
            chosen = self.run_menu(['  Favorite: /mnt/win (updated 17.05.2026) <-> cloud/me'])
        self.assertEqual(chosen, ('/mnt/win', 'cloud/me'))

    def test_the_known_replicas_with_disks_not_connected(self):
        self.known.note_seen('uuid:U:/eliran', '/mnt/win/eliran',
                             replicalog.Entry(datetime.date(2026, 5, 17), 'removed old money.ods\nremove Resume.*'),
                             datetime.datetime(2026, 10, 30, 9, 5))
        self.known.note_changed('uuid:U:/eliran', datetime.datetime(2026, 10, 30, 9, 30))
        self.known.note_seen('drive:R:/eliran', 'cloud/eliran', None, datetime.datetime(2026, 10, 29, 8, 0))
        shown = {}

        def dashboard(known=None, other_paths=()):
            shown['paths'] = other_paths
        with mock.patch('dirdelta.hashes_screen.dashboard', side_effect=dashboard):
            self.assertIsNone(self.run_menu([choose_replicas.KNOWN_LIST, 'Quit']))
        # The latest updated first
        self.assertEqual(shown['paths'], ['/mnt/win/eliran', 'cloud/eliran'])
        # In a section of its own, after the sorts
        self.assertEqual(self.menus[0][-3:], [choose_replicas.REPLICAS_SECTION, choose_replicas.KNOWN_LIST, 'Quit'])

    def test_what_is_known_of_a_replica(self):
        self.known.note_seen('uuid:U:/eliran', '/mnt/win/eliran',
                             replicalog.Entry(datetime.date(2026, 5, 17), 'removed old money.ods\nremove Resume.*'),
                             datetime.datetime(2026, 10, 30, 9, 5))
        self.known.note_changed('uuid:U:/eliran', datetime.datetime(2026, 10, 30, 9, 30))
        self.assertEqual(choose_replicas.known_lines(self.known.info_at('/mnt/win/eliran')), [
            '  Last update: 17.05.2026 - removed old money.ods (+1 more line)',
            '  Synced 30.10.2026 09:05; changed by dirdelta 30.10.2026 09:30'])

    def test_no_known_replicas_no_option(self):
        self.run_menu(['Quit'])
        self.assertNotIn(choose_replicas.KNOWN_LIST, self.menus[0])

if __name__ == '__main__':
    unittest.main()
