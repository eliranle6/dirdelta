import unittest

from dirdelta.util import text


class CountedTest(unittest.TestCase):
    def test_one_and_many(self):
        self.assertEqual(text.counted(1, 'error'), '1 error')
        self.assertEqual(text.counted(0, 'error'), '0 errors')
        self.assertEqual(text.counted(3, 'error'), '3 errors')


class FilesTest(unittest.TestCase):
    def test_one_or_more(self):
        self.assertEqual(text.files(1), "1 file")
        self.assertEqual(text.files(0), "0 files")
        self.assertEqual(text.files(17427), "17427 files")
        self.assertEqual(text.files(17427, grouped=True), "17,427 files")


class FormatAgeTest(unittest.TestCase):
    def test_in_its_largest_whole_unit(self):
        self.assertEqual([text.format_age(seconds) for seconds in (20, 60, 180, 7200, 86400, 9 * 86400, 200 * 86400,
                                                                   800 * 86400)],
                         ["just now", "1 minute ago", "3 minutes ago", "2 hours ago", "1 day ago", "1 week ago",
                          "6 months ago", "2 years ago"])


class ListedTest(unittest.TestCase):
    def test_cut_short_saying_how_many_more(self):
        self.assertEqual(text.listed(['a', 'b', 'c'], 2), ['a', 'b', '  (and 1 more)'])
        self.assertEqual(text.listed(['a', 'b'], 2), ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
