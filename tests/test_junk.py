import unittest

from dirdelta import junk


class JunkTest(unittest.TestCase):
    def test_by_name(self):
        for relpath in ['Thumbs.db', 'a/desktop.ini', '.DS_Store', 'trip/._IMG_1.jpg', '~$report.docx',
                        'x.tmp', 'movie.mkv.part', 'setup.crdownload', 'Setup.EXE', 'tool.msi', 'app.dmg']:
            self.assertIsNotNone(junk.why(relpath, 10), relpath)
        for relpath in ['report.docx', 'IMG_1.jpg', 'thumbs.db.txt', 'notes', 'a.zip', '.bashrc']:
            self.assertIsNone(junk.why(relpath, 10), relpath)

    def test_an_empty_file(self):
        self.assertEqual(junk.why('a.txt', 0), "an empty file")
        self.assertIsNone(junk.why('a.txt', None))

    def test_an_archive_unpacked_beside_it(self):
        found = junk.find(['photos.zip', 'photos/a.jpg', 'docs.tar.gz', 'docs/x/b.txt', 'music.zip', 'other/c.mp3'],
                          {})
        self.assertEqual(found, {'photos.zip': "an archive whose contents are beside it, in photos/",
                                 'docs.tar.gz': "an archive whose contents are beside it, in docs/"})

    def test_find_by_sizes(self):
        self.assertEqual(junk.find(['a.txt', 'b.txt', 'Thumbs.db'], {'a.txt': 0, 'b.txt': 3, 'Thumbs.db': 5}),
                         {'a.txt': "an empty file", 'Thumbs.db': "a Windows thumbnails cache"})


if __name__ == '__main__':
    unittest.main()
