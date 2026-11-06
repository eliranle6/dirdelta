"""When a photo was taken, by its format"""
import struct

from dirdelta.util.exif.formats import (CR3_EXTENSIONS, HEIF_EXTENSIONS, JPEG_EXTENSIONS, MAX_TIFF_HEADER,
                                        RAF_EXTENSIONS, TIFF_EXTENSIONS)
from dirdelta.util.exif.isobmff import _cr3_tiffs, _heif_exif
from dirdelta.util.exif.jpeg import _exif_segment, _raf_exif
from dirdelta.util.exif.tiff import _tiff_date


def date_taken(path):
    """When the photo at path was taken, 'YYYY-MM-DD HH:MM:SS', or None if it isn't one read here,
    has no date, or can't be read"""
    lower = path.lower()
    if not lower.endswith(JPEG_EXTENSIONS + HEIF_EXTENSIONS + TIFF_EXTENSIONS + CR3_EXTENSIONS +
                          RAF_EXTENSIONS):
        return None
    try:
        with open(path, 'rb') as f:
            if lower.endswith(JPEG_EXTENSIONS):
                tiffs = [_exif_segment(f)]
            elif lower.endswith(HEIF_EXTENSIONS):
                tiffs = [_heif_exif(f)]
            elif lower.endswith(CR3_EXTENSIONS):
                tiffs = _cr3_tiffs(f)
            elif lower.endswith(RAF_EXTENSIONS):
                tiffs = [_raf_exif(f)]
            else:
                tiffs = [f.read(MAX_TIFF_HEADER)]
    except (OSError, struct.error, IndexError, ValueError):
        return None
    for tiff in tiffs:
        if tiff is None:
            continue
        try:
            date = _tiff_date(tiff)
        except (struct.error, IndexError, KeyError, ValueError):
            date = None
        if date:
            return date
    return None
