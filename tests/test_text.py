import unittest

from dirdelta import text


class FilesTest(unittest.TestCase):
    def test_one_or_more(self):
        self.assertEqual(text.files(1), "1 file")
        self.assertEqual(text.files(0), "0 files")
        self.assertEqual(text.files(17427), "17427 files")
        self.assertEqual(text.files(17427, grouped=True), "17,427 files")


if __name__ == '__main__':
    unittest.main()
