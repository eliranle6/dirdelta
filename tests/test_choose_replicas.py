import unittest
from unittest import mock

from dirdelta import choose_replicas
from dirdelta import dirtree
from dirdelta import drivecache
from dirdelta import replicas
import helpers

NONE = choose_replicas.NOT_CHOSEN


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
        def pick_option(options, header=''):
            self.menus.append(options)
            return answers.pop(0)
        with mock.patch('dirdelta.picker.pick_option', side_effect=pick_option), \
                mock.patch('dirdelta.picker.pick_under_dir',
                           side_effect=lambda *_, **__: dir_picks.pop(0)) as self.pick_under_dir, \
                mock.patch('dirdelta.picker.pick_from_tree',
                           side_effect=lambda *_, **__: tree_picks.pop(0)) as self.pick_from_tree:
            return choose_replicas.run(self.known)

    def test_the_slots_start_not_chosen(self):
        self.assertIsNone(self.run_menu(['Quit']))
        self.assertEqual(self.menus, [['Replica A: ' + NONE, 'Replica B: ' + NONE, 'Quit']])

    def test_two_local_dirs(self):
        chosen = self.run_menu(['Replica A: ' + NONE, 'Local disk',
                                'Replica B: ' + NONE, 'Local disk'],
                               dir_picks=['/mnt/win', '/home/me'])
        self.assertEqual(chosen, ('/mnt/win', '/home/me'))
        self.assertEqual(self.menus[2], ['Replica A: /mnt/win', 'Replica B: ' + NONE, 'Quit'])
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
            chosen = self.run_menu(['Replica B: ' + NONE, 'Google Drive',
                                    'Replica A: ' + NONE, 'Local disk'],
                                   dir_picks=['/mnt/win'], tree_picks=[[music]])
        create.assert_called_once_with('cloud')
        self.assertEqual(chosen, ('/mnt/win', 'cloud/me/music'))
        self.assertTrue(self.pick_from_tree.call_args.kwargs['dirs_only'])

    def test_drives_top_is_cloud(self):
        tree = dirtree.DirTree('/')
        with mock.patch('dirdelta.utils.create_dirtree_from_arg', return_value=tree):
            chosen = self.run_menu(['Replica A: ' + NONE, 'Google Drive',
                                    'Replica B: ' + NONE, 'Local disk'],
                                   dir_picks=['/a'], tree_picks=[[tree.get_node('').data]])
        self.assertEqual(chosen, ('cloud', '/a'))

    def test_a_drive_cache_error_is_shown(self):
        with mock.patch('dirdelta.utils.create_dirtree_from_arg',
                        side_effect=drivecache.DriveCacheError('two folders named x')):
            self.assertIsNone(self.run_menu(['Replica A: ' + NONE, 'Google Drive', 'Quit']))
        self.assertEqual(self.show.call_args.args[1], ['two folders named x'])

    def test_quitting_a_pick_keeps_the_slot(self):
        self.run_menu(['Replica A: ' + NONE, 'Local disk', 'Replica A: ' + NONE, None, 'Quit'],
                      dir_picks=[None])
        self.assertEqual(self.menus[-1][0], 'Replica A: ' + NONE)

    def test_a_slot_can_be_chosen_again(self):
        chosen = self.run_menu(['Replica A: ' + NONE, 'Local disk', 'Replica A: /x', 'Local disk',
                                'Replica B: ' + NONE, 'Local disk'],
                               dir_picks=['/x', '/y', '/z'])
        self.assertEqual(chosen, ('/y', '/z'))

    def test_the_same_dir_twice_is_refused(self):
        self.run_menu(['Replica A: ' + NONE, 'Local disk', 'Replica B: ' + NONE, 'Local disk',
                       'Quit'], dir_picks=['/x', '/x'])
        self.assertEqual(self.show.call_args.args[0], 'Same replica')
        self.assertEqual(self.menus[-1][:2], ['Replica A: /x', 'Replica B: ' + NONE])

    def test_favorites_then_recent_pairs(self):
        self.known.record('/a', '/b')
        self.known.record('/mnt/win', 'cloud/me')
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        self.known.toggle_favorite('/f', '/g')
        self.known.record('/c', '/d')
        with mock.patch('os.path.isdir', return_value=True):
            chosen = self.run_menu(['Recent: /a <-> /b'])
        self.assertEqual(chosen, ('/a', '/b'))
        self.assertEqual(self.menus[0][2:], [
            'Favorite: /mnt/win <-> cloud/me',
            'Favorite: /f <-> /g',
            # Not the favorite again
            'Recent: /c <-> /d',
            'Recent: /a <-> /b',
            'Quit',
        ])

    def test_a_favorite_is_chosen_at_once(self):
        self.known.toggle_favorite('/mnt/win', 'cloud/me')
        with mock.patch('os.path.isdir', return_value=True):
            chosen = self.run_menu(['Favorite: /mnt/win <-> cloud/me'])
        self.assertEqual(chosen, ('/mnt/win', 'cloud/me'))

    def test_a_pair_whose_local_dir_is_gone_is_refused(self):
        self.known.record('/no/such/dir', 'cloud/me')
        self.assertIsNone(self.run_menu(['Recent: /no/such/dir <-> cloud/me', 'Quit']))
        title, lines = self.show.call_args.args[:2]
        self.assertEqual(title, 'No such directory')
        self.assertEqual(lines, ['/no/such/dir is not a directory (anymore?).'])
        # Back to the menu
        self.assertEqual(len(self.menus), 2)


if __name__ == '__main__':
    unittest.main()
