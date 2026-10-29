import os
import shutil
import struct
import tempfile
import unittest

from dirdelta import exif


def _jpeg(date=b'2024:07:01 14:03:22\0', order='<', tag=0x9003, before=b''):
    """A JPEG's start, with segments before (bytes) and an EXIF segment with date (in the EXIF IFD's
    tag, or IFD0's DateTime with tag 0x0132)"""
    marker = b'II' if order == '<' else b'MM'
    if tag == 0x0132:
        # IFD0 at 8: one entry, the date's text after it
        ifd0 = struct.pack(order + 'H', 1) + struct.pack(order + 'HHII', tag, 2, len(date), 8 + 2 + 12 + 4)
        tiff = marker + struct.pack(order + 'HI', 42, 8) + ifd0 + struct.pack(order + 'I', 0) + date
    else:
        # IFD0 at 8 pointing at the EXIF IFD after it, the date's text after that
        exif_ifd_offset = 8 + 2 + 12 + 4
        date_offset = exif_ifd_offset + 2 + 12 + 4
        ifd0 = struct.pack(order + 'H', 1) + struct.pack(order + 'HHII', 0x8769, 4, 1, exif_ifd_offset)
        exif_ifd = struct.pack(order + 'H', 1) + struct.pack(order + 'HHII', tag, 2, len(date), date_offset)
        tiff = (marker + struct.pack(order + 'HI', 42, 8) + ifd0 + struct.pack(order + 'I', 0) +
                exif_ifd + struct.pack(order + 'I', 0) + date)
    app1 = b'Exif\0\0' + tiff
    return b'\xff\xd8' + before + b'\xff\xe1' + struct.pack('>H', len(app1) + 2) + app1 + b'\xff\xda'


class DateTakenTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='dirdelta-exif-')
        self.addCleanup(shutil.rmtree, self.dir)

    def date(self, data, name='photo.jpg'):
        path = os.path.join(self.dir, name)
        with open(path, 'wb') as f:
            f.write(data)
        return exif.date_taken(path)

    def test_date_time_original(self):
        self.assertEqual(self.date(_jpeg()), '2024-07-01 14:03:22')

    def test_big_endian(self):
        self.assertEqual(self.date(_jpeg(order='>')), '2024-07-01 14:03:22')

    def test_after_other_segments(self):
        app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\0' + b'\0' * 9
        self.assertEqual(self.date(_jpeg(before=app0)), '2024-07-01 14:03:22')

    def test_ifd0s_date_time_if_theres_no_original(self):
        self.assertEqual(self.date(_jpeg(tag=0x0132)), '2024-07-01 14:03:22')

    def test_none_without_a_date(self):
        self.assertIsNone(self.date(_jpeg(tag=0x9004 + 100)))
        self.assertIsNone(self.date(_jpeg(date=b'0000:00:00 00:00:00\0')))
        self.assertIsNone(self.date(b'\xff\xd8\xff\xda'))

    def test_none_for_what_isnt_a_jpeg(self):
        self.assertIsNone(self.date(b'not a jpeg'))
        self.assertIsNone(self.date(_jpeg(), name='photo.heic'))
        self.assertIsNone(exif.date_taken(os.path.join(self.dir, 'missing.jpg')))

    def test_a_broken_exif_is_none(self):
        self.assertIsNone(self.date(_jpeg()[:30]))

    def test_upper_case_extension(self):
        self.assertEqual(self.date(_jpeg(), name='IMG.JPG'), '2024-07-01 14:03:22')

    def test_normalized(self):
        self.assertEqual(exif.normalized('2024:07:01 14:03:22'), '2024-07-01 14:03:22')
        self.assertIsNone(exif.normalized('yesterday'))


if __name__ == '__main__':
    unittest.main()
