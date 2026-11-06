"""A JPEG's EXIF segment, and a Fujifilm RAF's embedded JPEG's"""
import struct

from dirdelta.util.exif.formats import _RAF_JPEG_OFFSET, _RAF_MAGIC, _STANDALONE_MARKERS


def _exif_segment(f):
    """The TIFF data of the JPEG's EXIF segment (APP1, 'Exif\\0\\0'), reading only up to it, or None"""
    if f.read(2) != b'\xff\xd8':
        return None
    while True:
        marker = f.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        kind = marker[1]
        if kind in _STANDALONE_MARKERS:
            continue
        # Start of scan, or end of image: the image itself, with no EXIF before it
        if kind in (0xDA, 0xD9):
            return None
        length_bytes = f.read(2)
        if len(length_bytes) < 2:
            return None
        length = struct.unpack('>H', length_bytes)[0] - 2
        if kind == 0xE1:
            data = f.read(length)
            if data.startswith(b'Exif\0\0'):
                return data[6:]
        else:
            f.seek(length, 1)


def _raf_exif(f):
    """The TIFF data of a Fujifilm RAF's embedded JPEG's EXIF segment, or None"""
    header = f.read(_RAF_JPEG_OFFSET + 4)
    if not header.startswith(_RAF_MAGIC):
        return None
    f.seek(struct.unpack('>I', header[_RAF_JPEG_OFFSET:])[0])
    return _exif_segment(f)
