import unittest

from dirdelta import text


class FilesTest(unittest.TestCase):
    def test_one_or_more(self):
        self.assertEqual(text.files(1), "1 file")
        self.assertEqual(text.files(0), "0 files")
        self.assertEqual(text.files(17427), "17427 files")
        self.assertEqual(text.files(17427, grouped=True), "17,427 files")


class ListedTest(unittest.TestCase):
    def test_cut_short_saying_how_many_more(self):
        self.assertEqual(text.listed(['a', 'b', 'c'], 2), ['a', 'b', '  (and 1 more)'])
        self.assertEqual(text.listed(['a', 'b'], 2), ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
