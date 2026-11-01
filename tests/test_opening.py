import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import helpers
from dirdelta import clouddirtree
from dirdelta import localdiskdirtree
from dirdelta import opening
from dirdelta import picker

MB = 1024 * 1024


class OpenerTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-opening-'))
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['inbox/a.txt', 'inbox/trip/c.jpg'])
        patcher = mock.patch('dirdelta.opening.subprocess.Popen')
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('dirdelta.downloads.DOWNLOADS_DIR', os.path.join(self.root, 'downloads'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def opened(self):
        return [call.args[0][1] for call in self.popen.call_args_list]

    def local(self):
        return opening.Opener(localdiskdirtree.LocalDiskDirTree(self.root, True), 'inbox')

    def drive(self, sizes):
        """A Drive tree with files in its folder 'in' of sizes ({name: size}), and its opener; its
        fetch_file writes a file's size in bytes, saying it got half of it first, and the opener's
        status and tags then go to self.midway"""
        tree = clouddirtree.CloudDirTree('cloud/me')
        for name, size in sizes.items():
            tree.add_file_by_relpath('in/' + name)
            tree._infos['in/' + name] = clouddirtree.FileInfo(size, None, {}, None, False)
        self.midway = []
        opener = opening.Opener(tree, 'in')

        def fetch(relpath, local_path, progress=None):
            progress(tree.file_size(relpath) // 2)
            self.midway.append((opener.status(), opener.tags()))
            with open(local_path, 'wb') as f:
                f.write(b'x' * tree.file_size(relpath))
        patcher = mock.patch.object(tree, 'fetch_file', side_effect=fetch)
        self.fetch_file = patcher.start()
        self.addCleanup(patcher.stop)
        return opener

    def test_a_local_file_is_opened_in_a_session_of_its_own(self):
        opener = self.local()
        opener.open(['trip/c.jpg'], ['trip/c.jpg'])
        self.assertEqual(self.opened(), [os.path.join(self.root, 'inbox', 'trip', 'c.jpg')])
        self.assertEqual(self.popen.call_args.args[0][0], 'xdg-open')
        self.assertTrue(self.popen.call_args.kwargs['start_new_session'])
        self.assertEqual(opener.status_parts(), [('Opened c.jpg', opening.COLOR)])
        # A local file has no tag: it isn't downloaded
        self.assertEqual(opener.tags(), {})

    def test_a_local_dir_is_opened_too(self):
        opener = opening.Opener(localdiskdirtree.LocalDiskDirTree(self.root, True))
        opener.open(['inbox/trip'], [])
        self.assertEqual(self.opened(), [os.path.join(self.root, 'inbox', 'trip')])

    def test_several_local_files_at_once_arent_asked_about(self):
        opener = self.local()
        opener.press(['a.txt', 'trip/c.jpg'], ['a.txt', 'trip/c.jpg'])
        for _ in range(100):
            if opener.status() == 'Opened 2 files':
                break
            threading.Event().wait(0.01)
        self.assertEqual(len(self.opened()), 2)
        self.assertEqual(opener.status(), 'Opened 2 files')

    def test_what_couldnt_be_opened_is_said_for_a_while(self):
        opener = self.local()
        self.popen.side_effect = [FileNotFoundError('no xdg-open'), mock.DEFAULT]
        opener.open(['a.txt', 'trip/c.jpg'], ['a.txt', 'trip/c.jpg'])
        self.assertEqual(opener.status(), "Couldn't open a.txt: no xdg-open; opened c.jpg")
        with mock.patch('dirdelta.opening.time.monotonic', return_value=1e12):
            self.assertEqual(opener.status_parts(), [])

    def test_too_many_arent_opened(self):
        opener = self.local()
        with mock.patch('dirdelta.opening.MAX_OPENED', 1):
            opener.press(['a.txt', 'trip/c.jpg'], ['a.txt', 'trip/c.jpg'])
        self.assertEqual(self.opened(), [])
        self.assertEqual(opener.status(), "Can't open 2 files at once (at most 1): pick fewer")

    def test_a_drive_file_is_downloaded_first_with_its_progress_shown(self):
        opener = self.drive({'x.jpg': 4 * MB})
        opener.open(['x.jpg'], ['x.jpg'])
        self.assertEqual(self.fetch_file.call_args.args[0], 'in/x.jpg')
        self.assertEqual(self.midway, [("Downloading x.jpg to open it: 50% (2.0 MB of 4.0 MB)",
                                        {'x.jpg': opening.DOWNLOADING_TAG % (50,)})])
        path, = self.opened()
        self.assertTrue(path.startswith(os.path.join(self.root, 'downloads')))
        self.assertEqual(os.path.basename(path), 'x.jpg')
        self.assertEqual(opener.status(), 'Opened x.jpg')
        self.assertEqual(opener.tags(), {'x.jpg': opening.OPENED_TAG})
        # Then without its tag again
        with mock.patch('dirdelta.opening.time.monotonic', return_value=1e12):
            self.assertEqual(opener.tags(), {'x.jpg': ''})
        # Found downloaded the next time
        opener.open(['x.jpg'], ['x.jpg'])
        self.fetch_file.assert_called_once()

    def test_several_drive_files_are_asked_about_then_downloaded_one_after_another(self):
        opener = self.drive({'x.jpg': 2 * MB, 'y.jpg': 6 * MB})
        with mock.patch.object(opener, 'open_in_background') as open_in_background:
            opener.press(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
            open_in_background.assert_not_called()
            self.assertEqual(opener.status(), "Ctrl-X again: download 2 files (8.0 MB) into %s, and open them" %
                             (os.path.join(self.root, 'downloads'),))
            # Other files are asked about anew
            opener.press(['x.jpg'], ['x.jpg', 'y.jpg'])
            open_in_background.assert_called_once_with(['x.jpg'], ['x.jpg', 'y.jpg'])
            opener.press(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
            # Not soon after: asked again
            with mock.patch('dirdelta.opening.time.monotonic', return_value=1e12):
                opener.press(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
            self.assertEqual(open_in_background.call_count, 1)
            opener.press(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
            open_in_background.assert_called_with(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
        opener.open(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
        self.assertEqual(self.midway, [
            ("Downloading to open: 1 of 2 files, 12% (1.0 MB of 8.0 MB)",
             {'x.jpg': opening.DOWNLOADING_TAG % (50,), 'y.jpg': opening.WAITING_TAG}),
            ("Downloading to open: 2 of 2 files, 62% (5.0 MB of 8.0 MB)",
             {'x.jpg': opening.OPENED_TAG, 'y.jpg': opening.DOWNLOADING_TAG % (50,)})])
        self.assertEqual(opener.status(), 'Opened 2 files')
        # Downloaded now: nothing to ask
        self.assertIsNone(opener.question(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg']))

    def test_the_menus_open_asks_on_a_screen(self):
        opener = self.drive({'x.jpg': 2 * MB, 'y.jpg': 6 * MB})
        with mock.patch('dirdelta.picker.pick_option', return_value=opening.CONFIRM_NO) as pick_option:
            self.assertFalse(opening.confirm(opener, ['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg']))
        lines = pick_option.call_args.kwargs['header'].split('\n')
        self.assertEqual(lines, ["Open 2 files? First, download 2 files (8.0 MB) into %s:" %
                                 (os.path.join(self.root, 'downloads'),),
                                 "  x.jpg (2.0 MB)", "  y.jpg (6.0 MB)"])
        self.assertEqual(pick_option.call_args.args[0], [opening.CONFIRM_NO, opening.CONFIRM_YES])
        with mock.patch('dirdelta.picker.pick_option') as pick_option:
            self.assertTrue(opening.confirm(opener, ['x.jpg'], ['x.jpg', 'y.jpg']))
        pick_option.assert_not_called()

    def test_a_drive_folder_cant_be_opened(self):
        opener = self.drive({'x.jpg': 3})
        opener.open([''], ['x.jpg'])
        self.assertEqual(opener.status(), "Couldn't open in: a Google Drive folder can't be opened here")

    def test_with_tags_adds_them_after_the_files_texts(self):
        opener = self.drive({'x.jpg': 4 * MB, 'y.jpg': 4 * MB})
        opener._enqueue(['x.jpg', 'y.jpg'], ['x.jpg', 'y.jpg'])
        shown = opening.with_tags({'x.jpg': 'x.jpg  [hashed]', '': 'status'}, opener, lambda relpath: relpath + '!')
        self.assertEqual({relpath: picker.unstyled(text) for relpath, text in shown.items()},
                         {'x.jpg': 'x.jpg  [hashed]  ' + opening.WAITING_TAG,
                          'y.jpg': 'y.jpg!  ' + opening.WAITING_TAG, '': 'status'})
        # In grey while waiting, in orange while downloading
        self.assertEqual(shown['y.jpg'], 'y.jpg!' + picker.styled([('  ', None), (opening.WAITING_TAG, 'grey')]))
        self.assertEqual(opening.tag_style(opening.DOWNLOADING_TAG % (50,)), 'orange')


if __name__ == '__main__':
    unittest.main()
