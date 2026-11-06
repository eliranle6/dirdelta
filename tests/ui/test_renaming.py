import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import renaming


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-renaming-'))
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['a.txt', 'trip/b.jpg', 'trip/deep/c.jpg'])
        os.makedirs(os.path.join(self.root, 'empty'))
        self.tree = localdiskdirtree.LocalDiskDirTree(self.root, True)
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'), mock.patch('dirdelta.ui.messages.show'),
                        mock.patch('dirdelta.ui.messages.progress_screen'), mock.patch('dirdelta.util.dryrun.DRYRUN', False)):
            self.addCleanup(patcher.stop)
            patcher.start()

    def rename(self, relpath, answer):
        with mock.patch('dirdelta.ui.messages.ask', return_value=answer) as ask:
            renamed = renaming.rename(self.tree, relpath)
        self.ask = ask
        return renamed

    def test_on_a_read_only_dir_its_said_before_asking_for_a_name(self):
        with mock.patch('dirdelta.trees.localdiskdirtree.fs.os.access', return_value=False), \
                mock.patch('dirdelta.ui.messages.show') as show:
            self.assertIsNone(self.rename('a.txt', 'b.txt'))
        self.ask.assert_not_called()
        self.assertEqual(show.call_args.args[0], "Can't rename it")
        self.assertIn('read-only', show.call_args.args[1][0])

    def exists(self, relpath):
        return os.path.exists(os.path.join(self.root, relpath))

    def test_a_file_starting_as_its_name(self):
        self.assertEqual(self.rename('trip/b.jpg', 'beach.jpg'), ('trip/beach.jpg', [('trip/b.jpg', 'trip/beach.jpg')]))
        self.assertEqual(self.ask.call_args.args[3], 'b.jpg')
        self.assertTrue(self.exists('trip/beach.jpg'))
        self.assertFalse(self.exists('trip/b.jpg'))

    def test_a_dir_with_all_in_it(self):
        self.assertEqual(self.rename('trip', '2024 trip'),
                         ('2024 trip', [('trip/b.jpg', '2024 trip/b.jpg'), ('trip/deep/c.jpg', '2024 trip/deep/c.jpg')]))
        self.assertTrue(self.exists('2024 trip/deep/c.jpg'))
        self.assertFalse(self.exists('trip'))

    def test_an_empty_dir(self):
        self.assertEqual(self.rename('empty', 'full'), ('full', []))
        self.assertTrue(os.path.isdir(os.path.join(self.root, 'full')))

    def test_no_name_the_same_one_or_one_that_cant_be(self):
        for answer in (None, 'a.txt', 'x/y', '..', 'trip'):
            self.assertIsNone(self.rename('a.txt', answer), answer)
        self.assertTrue(self.exists('a.txt'))
        # The root can't be
        self.assertIsNone(self.rename('', 'x'))
        self.ask.assert_not_called()

    def test_a_dry_run_changes_nothing(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            self.assertEqual(self.rename('trip', 'x'), ('x', [('trip/b.jpg', 'x/b.jpg'), ('trip/deep/c.jpg', 'x/deep/c.jpg')]))
        self.assertTrue(self.exists('trip/b.jpg'))
        self.assertFalse(self.exists('x'))


if __name__ == '__main__':
    unittest.main()
