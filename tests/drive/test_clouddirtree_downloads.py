"""Copying a Drive tree's files out of it, and their thumbnails"""
import os
import unittest
from unittest import mock

from dirdelta.drive import clouddirtree
from clouddirtree_support import CloudDirTreeChangesTest, _http_error


class DownloadsTest(CloudDirTreeChangesTest):
    """Downloads and thumbnails"""

    def test_a_thumbnail_is_got_at_the_size_asked_for(self):
        self.service.files.return_value.get.return_value.execute.return_value = {
            'thumbnailLink': 'https://lh3.example/t/abc=s220'}
        with mock.patch('dirdelta.drive.driveapi.get_url', return_value=b'png') as get_url:
            self.assertEqual(self.tree.thumbnail('album/track.mp3', 300), b'png')
        self.service.files.return_value.get.assert_called_once_with(fileId='track', fields='thumbnailLink')
        get_url.assert_called_once_with('https://lh3.example/t/abc=s300')

    def test_no_thumbnail(self):
        self.service.files.return_value.get.return_value.execute.return_value = {}
        with mock.patch('dirdelta.drive.driveapi.get_url') as get_url:
            self.assertIsNone(self.tree.thumbnail('album/track.mp3', 300))
            self.assertIsNone(self.tree.thumbnail('not/there.jpg', 300))
            self.service.files.return_value.get.return_value.execute.side_effect = _http_error()
            self.assertIsNone(self.tree.thumbnail('album/track.mp3', 300))
        get_url.assert_not_called()

    def test_download(self):
        def downloader(local_file, request):
            local_file.write(b'track content')
            return mock.Mock(next_chunk=mock.Mock(return_value=(None, True)))
        with mock.patch('dirdelta.drive.clouddirtree.fetching.MediaIoBaseDownload', side_effect=downloader):
            local = self.download_to_local_dir(['album/track.mp3'])
        self.service.files.return_value.get_media.assert_called_once_with(fileId='track')
        with open(os.path.join(self.local_dir, 'album', 'track.mp3'), 'rb') as f:
            self.assertEqual(f.read(), b'track content')
        self.assertIn('album/track.mp3', local)

    def test_a_download_with_progress_says_how_far_it_got_after_each_chunk(self):
        made = {}

        def downloader(local_file, request, chunksize=None):
            made['chunksize'] = chunksize
            local_file.write(b'track content')
            return mock.Mock(next_chunk=mock.Mock(side_effect=[(mock.Mock(resumable_progress=5), False),
                                                               (mock.Mock(resumable_progress=13), True)]))
        got = []
        with mock.patch('dirdelta.drive.clouddirtree.fetching.MediaIoBaseDownload', side_effect=downloader):
            self.tree.fetch_file('album/track.mp3', os.path.join(self.local_dir, 'track.mp3'), progress=got.append)
        self.assertEqual(got, [5, 13])
        self.assertEqual(made['chunksize'], clouddirtree.fetching.PROGRESS_CHUNK_SIZE)

    def test_a_download_gets_drives_modification_time(self):
        self.tree._infos['album/track.mp3'] = self.tree._info('album/track.mp3')._replace(modified=1719842602)
        def downloader(local_file, request):
            local_file.write(b'track content')
            return mock.Mock(next_chunk=mock.Mock(return_value=(None, True)))
        with mock.patch('dirdelta.drive.clouddirtree.fetching.MediaIoBaseDownload', side_effect=downloader):
            self.download_to_local_dir(['album/track.mp3'])
        self.assertEqual(os.path.getmtime(os.path.join(self.local_dir, 'album', 'track.mp3')), 1719842602)

    def test_a_google_file_isnt_copied_to_a_dir_and_the_rest_are(self):
        self.tree.add_file_by_relpath('Budget.gsheet')
        self.tree._cloud_ids['Budget.gsheet'] = 'sheet'
        self.tree._infos['Budget.gsheet'] = clouddirtree.FileInfo(None, None, {}, None, True)
        def downloader(local_file, request):
            local_file.write(b'content')
            return mock.Mock(next_chunk=mock.Mock(return_value=(None, True)))
        with mock.patch('dirdelta.drive.clouddirtree.fetching.MediaIoBaseDownload', side_effect=downloader):
            local = self.download_to_local_dir(['Budget.gsheet', 'song.mp3'])
        self.assertEqual(os.listdir(self.local_dir), ['song.mp3'])
        self.assertNotIn('Budget.gsheet', local)
        self.assertTrue(any(line.startswith('Skipped Budget.gsheet') for line in self.lines()))
        self.assertIn('Copy complete: copied 1 of 2 files to %s' % (os.path.realpath(self.local_dir),),
                      self.lines())

    def test_a_failed_download_leaves_no_file_and_the_rest_go_on(self):
        def downloader(local_file, request):
            local_file.write(b'part of it')
            return mock.Mock(next_chunk=mock.Mock(side_effect=_http_error()))
        with mock.patch('dirdelta.drive.clouddirtree.fetching.MediaIoBaseDownload', side_effect=downloader):
            local = self.download_to_local_dir(['song.mp3', 'album/track.mp3'])
        self.assertEqual(os.listdir(self.local_dir), ['album'])
        self.assertEqual(os.listdir(os.path.join(self.local_dir, 'album')), [])
        self.assertNotIn('song.mp3', local)


if __name__ == '__main__':
    unittest.main()
