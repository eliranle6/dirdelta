"""When a photo was taken, from its EXIF data (DateTimeOriginal), read from a JPEG's header: enough
to tell two photos of the same name apart, without a library for it. Other formats (HEIC, raw) aren't
read: their date is unknown."""
import struct

# The extensions of the files read (others aren't, to save reading them)
JPEG_EXTENSIONS = ('.jpg', '.jpeg', '.jpe')
# EXIF tags: the IFD of the EXIF ones, and the dates in it (and IFD0's, a fallback)
_EXIF_IFD_TAG = 0x8769
_DATE_TIME_ORIGINAL_TAG = 0x9003
_DATE_TIME_TAG = 0x0132
# A JPEG segment marker without a length after it
_STANDALONE_MARKERS = set(range(0xD0, 0xDA)) | {0x01}


def date_taken(path):
    """When the JPEG photo at path was taken, 'YYYY-MM-DD HH:MM:SS', or None if it isn't a JPEG, has
    no date, or can't be read"""
    if not path.lower().endswith(JPEG_EXTENSIONS):
        return None
    try:
        with open(path, 'rb') as f:
            exif = _exif_segment(f)
    except OSError:
        return None
    if exif is None:
        return None
    try:
        return _tiff_date(exif)
    except (struct.error, IndexError, ValueError):
        return None


def normalized(date):
    """An EXIF date ('YYYY:MM:DD HH:MM:SS', as Drive gives it too) as 'YYYY-MM-DD HH:MM:SS', or None
    if it isn't one"""
    date = date.strip().rstrip('\0')
    if len(date) < 19 or date[4] != ':' or date[7] != ':' or not date[:4].isdigit() or date.startswith('0000'):
        return None
    return date[:4] + '-' + date[5:7] + '-' + date[8:19]


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


def _tiff_date(tiff):
    order = {b'II': '<', b'MM': '>'}[tiff[:2]]

    def entries(offset):
        """{tag: (type, count, value or offset)} of the IFD at offset"""
        count = struct.unpack(order + 'H', tiff[offset:offset + 2])[0]
        found = {}
        for i in range(count):
            entry = offset + 2 + 12 * i
            tag, kind, nr_values = struct.unpack(order + 'HHI', tiff[entry:entry + 8])
            found[tag] = (kind, nr_values, tiff[entry + 8:entry + 12])
        return found

    def text(entry):
        kind, nr_values, value = entry
        if nr_values <= 4:
            data = value[:nr_values]
        else:
            offset = struct.unpack(order + 'I', value)[0]
            data = tiff[offset:offset + nr_values]
        return data.decode('ascii', 'replace')

    ifd0 = entries(struct.unpack(order + 'I', tiff[4:8])[0])
    if _EXIF_IFD_TAG in ifd0:
        exif_ifd = entries(struct.unpack(order + 'I', ifd0[_EXIF_IFD_TAG][2])[0])
        if _DATE_TIME_ORIGINAL_TAG in exif_ifd:
            date = normalized(text(exif_ifd[_DATE_TIME_ORIGINAL_TAG]))
            if date:
                return date
    if _DATE_TIME_TAG in ifd0:
        return normalized(text(ifd0[_DATE_TIME_TAG]))
    return None
