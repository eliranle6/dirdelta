import argparse
import unittest
from unittest import mock

from dirdelta.screens import choose_replicas
from dirdelta import main
from dirdelta.known import replicas


def _args(**kwargs):
    return argparse.Namespace(**dict(dict(dir_a_path=None, dir_b_path=None, execute=None, sort=False, max_depth=20),
                                     **kwargs))


class StartMenuTest(unittest.TestCase):
    def run_menu(self, chosen, mounted, are_there=True):
        """_run() from the start menu, which chooses each of chosen in turn, then quits; a volume's
        mount is checked through mounted, a list of answers"""
        self.asked = []

        def ensure_mounted(path):
            self.asked.append(path)
            return mounted.pop(0)
        with mock.patch('dirdelta.known.replicas.load', return_value=replicas.Replicas()), \
                mock.patch('dirdelta.screens.choose_replicas.run', side_effect=list(chosen) + [None]), \
                mock.patch('dirdelta.known.mounts.ensure_mounted', side_effect=ensure_mounted), \
                mock.patch('dirdelta.known.mounts.remember'), \
                mock.patch('dirdelta.known.replicanames.forget'), \
                mock.patch('dirdelta.screens.choose_replicas.are_there', return_value=are_there) as self.are_there, \
                mock.patch('dirdelta.sync.dirsync_main.run') as self.sync, \
                mock.patch('dirdelta.inbox.inbox.run') as self.sort:
            return main._run(_args())

    def test_a_pairs_volumes_are_checked_once_then_its_dirs(self):
        self.run_menu([('/mnt/win', 'cloud/me')], [True, True])
        self.assertEqual(self.asked, ['/mnt/win', 'cloud/me'])
        self.are_there.assert_called_once_with(('/mnt/win', 'cloud/me'))
        self.assertEqual(self.sync.call_args.args[0].dir_a_path, '/mnt/win')

    def test_a_pair_on_a_volume_not_mounted_is_back_to_the_menu(self):
        self.run_menu([('/mnt/win', 'cloud/me')], [False])
        # Going back from the first, the second isn't asked about, nor the dirs looked for
        self.assertEqual(self.asked, ['/mnt/win'])
        self.are_there.assert_not_called()
        self.sync.assert_not_called()

    def test_a_pair_whose_dir_is_gone_is_back_to_the_menu(self):
        self.run_menu([('/mnt/win', 'cloud/me')], [True, True], are_there=False)
        self.sync.assert_not_called()

    def test_a_sort_is_checked_as_a_pair_is(self):
        self.run_menu([choose_replicas.Sort('/in', '/root')], [True, True])
        self.assertEqual(self.asked, ['/in', '/root'])
        self.sort.assert_called_once()
        self.run_menu([choose_replicas.Sort('/in', '/root')], [True, True], are_there=False)
        self.sort.assert_not_called()


if __name__ == '__main__':
    unittest.main()
