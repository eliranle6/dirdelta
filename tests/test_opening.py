import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import clouddirtree
from dirdelta import localdiskdirtree
from dirdelta import opening


class OpenerTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-opening-'))
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['inbox/a.txt', 'inbox/trip/c.jpg'])
        patcher = mock.patch('dirdelta.opening.subprocess.Popen')
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)

    def opened(self):
        return [call.args[0] for call in self.popen.call_args_list]

    def test_a_local_file_is_opened_in_a_session_of_its_own(self):
        opener = opening.Opener(localdiskdirtree.LocalDiskDirTree(self.root, True), 'inbox')
        opener.open(['trip/c.jpg'], ['trip/c.jpg'])
        self.assertEqual(self.opened(), [['xdg-open', os.path.join(self.root, 'inbox', 'trip', 'c.jpg')]])
        self.assertTrue(self.popen.call_args.kwargs['start_new_session'])
        self.assertEqual(opener.status(), 'Opened c.jpg')
        self.assertEqual(opener.status_parts(), [('Opened c.jpg', opening.COLOR)])

    def test_a_local_dir_is_opened_too(self):
        opener = opening.Opener(localdiskdirtree.LocalDiskDirTree(self.root, True))
        opener.open(['inbox/trip'], [])
        self.assertEqual(self.opened(), [['xdg-open', os.path.join(self.root, 'inbox', 'trip')]])

    def test_several_files_one_after_another(self):
        opener = opening.Opener(localdiskdirtree.LocalDiskDirTree(self.root, True), 'inbox')
        thread = opener.open_in_background(['a.txt', 'trip/c.jpg'], ['a.txt', 'trip/c.jpg'])
        thread.join()
        self.assertEqual(len(self.opened()), 2)
        self.assertEqual(opener.status(), 'Opened 2 files')

    def test_what_couldnt_be_opened_is_said_for_a_while(self):
        opener = opening.Opener(localdiskdirtree.LocalDiskDirTree(self.root, True), 'inbox')
        self.popen.side_effect = [FileNotFoundError('no xdg-open'), mock.DEFAULT]
        opener.open(['a.txt', 'trip/c.jpg'], ['a.txt', 'trip/c.jpg'])
        self.assertEqual(opener.status(), "Couldn't open a.txt: no xdg-open; opened c.jpg")
        with mock.patch('dirdelta.opening.time.monotonic', return_value=1e12):
            self.assertEqual(opener.status(), '')
            self.assertEqual(opener.status_parts(), [])

    def test_a_drive_file_is_downloaded_first_and_a_folder_cant_be_opened(self):
        tree = clouddirtree.CloudDirTree('cloud/me')
        tree.add_file_by_relpath('in/x.jpg')
        tree._sizes['in/x.jpg'] = 3

        def fetch(relpath, local_path):
            with open(local_path, 'w') as f:
                f.write('abc')
        with mock.patch('dirdelta.downloads.DOWNLOADS_DIR', os.path.join(self.root, 'downloads')), \
                mock.patch.object(tree, 'fetch_file', side_effect=fetch) as fetch_file:
            opener = opening.Opener(tree, 'in')
            opener.open(['x.jpg'], ['x.jpg'])
            fetch_file.assert_called_once()
            self.assertEqual(fetch_file.call_args.args[0], 'in/x.jpg')
            path, = [args[1] for args in self.opened()]
            self.assertTrue(path.startswith(os.path.join(self.root, 'downloads')))
            self.assertEqual(os.path.basename(path), 'x.jpg')
            # Found downloaded the next time
            opener.open(['x.jpg'], ['x.jpg'])
            fetch_file.assert_called_once()
            opener.open([''], ['x.jpg'])
        self.assertEqual(opener.status(), "Couldn't open in: a Google Drive folder can't be opened here")


if __name__ == '__main__':
    unittest.main()
