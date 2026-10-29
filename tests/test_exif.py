import os
import shutil
import struct
import tempfile
import unittest

from dirdelta import exif


def _tiff(date=b'2024:07:01 14:03:22\0', order='<', tag=0x9003):
    """EXIF's TIFF data with date (in the EXIF IFD's tag, or IFD0's DateTime with tag 0x0132)"""
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
    return tiff


def _jpeg(date=b'2024:07:01 14:03:22\0', order='<', tag=0x9003, before=b''):
    """A JPEG's start, with segments before (bytes) and an EXIF segment with date (see _tiff())"""
    app1 = b'Exif\0\0' + _tiff(date, order, tag)
    return b'\xff\xd8' + before + b'\xff\xe1' + struct.pack('>H', len(app1) + 2) + app1 + b'\xff\xda'


def _box(kind, data, version=None):
    """An ISO BMFF box (a full box with version)"""
    if version is not None:
        data = bytes([version, 0, 0, 0]) + data
    return struct.pack('>I4s', 8 + len(data), kind) + data


def _heif(tiff, iloc_version=0):
    """A HEIF file's boxes, with an EXIF item holding tiff (after its header, past 'Exif\\0\\0')"""
    payload = struct.pack('>I', 6) + b'Exif\0\0' + tiff
    ftyp = _box(b'ftyp', b'heic\0\0\0\0mif1heic')
    # A picture's item first, then the EXIF one
    infe = (_box(b'infe', struct.pack('>HH', 1, 0) + b'hvc1\0', version=2) +
            _box(b'infe', struct.pack('>HH', 2, 0) + b'Exif\0', version=2))
    iinf = _box(b'iinf', struct.pack('>H', 2) + infe, version=0)

    def meta(offset):
        if iloc_version == 0:
            items = (struct.pack('>HHHII', 1, 0, 1, 0, 0) +
                     struct.pack('>HHHII', 2, 0, 1, offset, len(payload)))
        else:
            items = (struct.pack('>HHHHII', 1, 0, 0, 1, 0, 0) +
                     struct.pack('>HHHHII', 2, 0, 0, 1, offset, len(payload)))
        iloc = _box(b'iloc', bytes([0x44, 0x00]) + struct.pack('>H', 2) + items, version=iloc_version)
        return _box(b'meta', _box(b'hdlr', b'\0' * 4 + b'pict' + b'\0' * 13, version=0) + iinf + iloc,
                    version=0)
    offset = len(ftyp) + len(meta(0)) + 8
    return ftyp + meta(offset) + _box(b'mdat', payload)


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
        self.assertIsNone(self.date(_jpeg(), name='photo.png'))
        self.assertIsNone(exif.date_taken(os.path.join(self.dir, 'missing.jpg')))

    def test_a_broken_exif_is_none(self):
        self.assertIsNone(self.date(_jpeg()[:30]))

    def test_heic(self):
        self.assertEqual(self.date(_heif(_tiff()), name='IMG.HEIC'), '2024-07-01 14:03:22')
        self.assertEqual(self.date(_heif(_tiff(order='>'), iloc_version=1), name='x.heif'),
                         '2024-07-01 14:03:22')

    def test_a_heic_without_exif_or_broken_is_none(self):
        self.assertIsNone(self.date(_box(b'ftyp', b'heic\0\0\0\0') + _box(b'mdat', b'x'), name='x.heic'))
        self.assertIsNone(self.date(_heif(_tiff())[:60], name='x.heic'))

    def test_upper_case_extension(self):
        self.assertEqual(self.date(_jpeg(), name='IMG.JPG'), '2024-07-01 14:03:22')

    def test_normalized(self):
        self.assertEqual(exif.normalized('2024:07:01 14:03:22'), '2024-07-01 14:03:22')
        self.assertIsNone(exif.normalized('yesterday'))


if __name__ == '__main__':
    unittest.main()
