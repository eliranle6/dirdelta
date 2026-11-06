import os
import tempfile
import unittest
import zipfile
from unittest import mock

from dirdelta.screens import archive_screen


class ExploreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, 'z.zip')
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('in/side.txt', 'hello')
        for name, patcher in (('show', mock.patch('dirdelta.ui.messages.show')),
                              ('view', mock.patch('dirdelta.ui.picker.view_files')),
                              ('line', mock.patch('dirdelta.ui.messages.print_line'))):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def explore(self, relpath='d/z.zip', local_path=None):
        archive_screen.explore(relpath, {relpath}, local_path or (lambda: self.path))

    def test_its_files_are_shown_with_what_is_known(self):
        self.explore()
        self.assertEqual(self.view.call_args.args[:2], ('z.zip', ['in/side.txt']))
        self.assertIn('Size: 5 B', self.view.call_args.kwargs['previews']['in/side.txt'])

    def test_only_a_zip_of_the_files(self):
        archive_screen.explore('a.txt', {'a.txt'}, None)
        archive_screen.explore('d', {'d/z.zip'}, None)
        self.assertEqual([call.args[0] for call in self.show.call_args_list], ['Not a zip', 'Not a zip'])
        self.view.assert_not_called()

    def test_one_that_cant_be_read_says_why(self):
        with open(self.path, 'w') as f:
            f.write('not a zip')
        self.explore()
        self.assertEqual(self.show.call_args.args[0], "Can't look in d/z.zip")
        self.view.assert_not_called()

    def test_a_failed_download_says_why(self):
        def fail():
            raise OSError("no network")
        self.explore(local_path=fail)
        self.assertIn('no network', self.show.call_args.args[1][0])

    def test_an_empty_one(self):
        with zipfile.ZipFile(self.path, 'w'):
            pass
        self.explore()
        self.assertEqual(self.show.call_args.args[1], ["It's an empty zip."])
        self.view.assert_not_called()


if __name__ == '__main__':
    unittest.main()
