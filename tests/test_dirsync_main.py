import unittest
from unittest import mock

from dirdelta import dirsync_main
from dirdelta import dirtree


class WarnAboutScanErrorsTest(unittest.TestCase):
    def warnings(self, scan_errors):
        tree = dirtree.DirTree('/some/dir')
        tree.scan_errors = scan_errors
        with mock.patch('dirdelta.messages.print_line') as print_line:
            dirsync_main.warn_about_scan_errors(tree)
        return [call.args[0] for call in print_line.call_args_list]

    def test_no_errors_no_warning(self):
        self.assertEqual(self.warnings([]), [])

    def test_trees_without_scan_errors_get_no_warning(self):
        # E.g. cloud trees, which aren't scanned with find
        with mock.patch('dirdelta.messages.print_line') as print_line:
            dirsync_main.warn_about_scan_errors(dirtree.DirTree('cloud/mein'))
        print_line.assert_not_called()

    def test_errors_are_listed(self):
        lines = self.warnings(["find: '/some/dir/a': Permission denied"])
        self.assertEqual(lines, [
            "Warning: find couldn't read everything in /some/dir (1 errors), so the diff may be wrong:",
            "  find: '/some/dir/a': Permission denied",
        ])

    def test_only_the_first_errors_are_listed(self):
        errors = ["find: '/some/dir/%d': Permission denied" % (i,) for i in range(5)]
        lines = self.warnings(errors)
        self.assertEqual(len(lines), 1 + dirsync_main.MAX_SCAN_ERRORS_SHOWN + 1)
        self.assertIn('(5 errors)', lines[0])
        self.assertEqual(lines[-1], '  (and 2 more)')


if __name__ == '__main__':
    unittest.main()
