"""When a photo was taken, from its EXIF data (DateTimeOriginal), read from a JPEG's header, a HEIF
(HEIC) file's EXIF item, or a TIFF-based raw photo's (CR2, NEF, ARW, DNG, ...) IFDs: enough to tell
two photos of the same name apart, without a library for it. Other formats (CR3, RAF) aren't read:
their date is unknown."""
import os
import struct

# The extensions of the files read (others aren't, to save reading them)
JPEG_EXTENSIONS = ('.jpg', '.jpeg', '.jpe')
HEIF_EXTENSIONS = ('.heic', '.heif')
# Raw photos that are TIFF files (with their own magic numbers, some: ORF's, RW2's), and TIFFs
TIFF_EXTENSIONS = ('.cr2', '.nef', '.nrw', '.arw', '.srf', '.sr2', '.dng', '.orf', '.rw2', '.pef',
                   '.srw', '.3fr', '.erf', '.kdc', '.mef', '.mos', '.iiq', '.tif', '.tiff')
# How much of a TIFF file's start is read: its IFD0 and EXIF IFD are near it
MAX_TIFF_HEADER = 1 << 20
# The most of a HEIF file's EXIF item read
MAX_EXIF_SIZE = 1 << 20
# EXIF tags: the IFD of the EXIF ones, and the dates in it (and IFD0's, a fallback)
_EXIF_IFD_TAG = 0x8769
_DATE_TIME_ORIGINAL_TAG = 0x9003
_DATE_TIME_TAG = 0x0132
# A JPEG segment marker without a length after it
_STANDALONE_MARKERS = set(range(0xD0, 0xDA)) | {0x01}


def date_taken(path):
    """When the JPEG or HEIF photo at path was taken, 'YYYY-MM-DD HH:MM:SS', or None if it isn't one,
    has no date, or can't be read"""
    lower = path.lower()
    if not lower.endswith(JPEG_EXTENSIONS + HEIF_EXTENSIONS + TIFF_EXTENSIONS):
        return None
    try:
        with open(path, 'rb') as f:
            if lower.endswith(JPEG_EXTENSIONS):
                exif = _exif_segment(f)
            elif lower.endswith(HEIF_EXTENSIONS):
                exif = _heif_exif(f)
            else:
                exif = f.read(MAX_TIFF_HEADER)
    except (OSError, struct.error, IndexError, ValueError):
        return None
    if exif is None:
        return None
    try:
        return _tiff_date(exif)
    except (struct.error, IndexError, KeyError, ValueError):
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


def _heif_exif(f):
    """The TIFF data of a HEIF file's EXIF item, or None: the item whose type is 'Exif' (meta box's
    iinf), at where its extents are in the file (iloc), after its header (the offset of the TIFF
    header in it, often past an 'Exif\\0\\0')"""
    end = os.fstat(f.fileno()).st_size
    meta = next(((start, box_end) for kind, start, box_end in _boxes(f, 0, end) if kind == b'meta'), None)
    if meta is None:
        return None
    # A full box: its version and flags first
    children = {kind: (start, box_end) for kind, start, box_end in _boxes(f, meta[0] + 4, meta[1])}
    if b'iinf' not in children or b'iloc' not in children:
        return None
    item_id = _exif_item_id(f, *children[b'iinf'])
    if item_id is None:
        return None
    start, box_end = children[b'iloc']
    f.seek(start)
    extents = _item_extents(f.read(box_end - start), item_id)
    if not extents:
        return None
    data = b''
    for offset, length in extents:
        f.seek(offset)
        data += f.read(min(length, MAX_EXIF_SIZE - len(data)))
    header_offset = struct.unpack('>I', data[:4])[0]
    return data[4 + header_offset:]


def _boxes(f, start, end):
    """Yield (type, data start, end) of the ISO BMFF boxes in f from start to end"""
    position = start
    while position + 8 <= end:
        f.seek(position)
        size, kind = struct.unpack('>I4s', f.read(8))
        header_size = 8
        if size == 1:
            size = struct.unpack('>Q', f.read(8))[0]
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size:
            return
        yield kind, position + header_size, min(position + size, end)
        position += size


def _exif_item_id(f, start, end):
    """The id of the item of type 'Exif' in the iinf box from start to end, or None"""
    f.seek(start)
    version = f.read(4)[0]
    entries_start = start + 4 + (2 if version == 0 else 4)
    for kind, infe_start, _ in _boxes(f, entries_start, end):
        if kind != b'infe':
            continue
        f.seek(infe_start)
        infe_version = f.read(4)[0]
        if infe_version < 2:
            continue
        item_id = struct.unpack('>H' if infe_version == 2 else '>I', f.read(2 if infe_version == 2 else 4))[0]
        # The protection index, then the type
        f.read(2)
        if f.read(4) == b'Exif':
            return item_id
    return None


def _item_extents(iloc, wanted_id):
    """The (offset in the file, length) of each extent of the item with wanted_id, from an iloc box's
    data, or none if it's not there or not in the file itself (construction method 0)"""
    version = iloc[0]
    offset_size, length_size = iloc[4] >> 4, iloc[4] & 0xF
    base_offset_size = iloc[5] >> 4
    index_size = iloc[5] & 0xF if version in (1, 2) else 0
    position = 6

    def read(nr_bytes):
        nonlocal position
        value = int.from_bytes(iloc[position:position + nr_bytes], 'big') if nr_bytes else 0
        position += nr_bytes
        return value

    for _ in range(read(2 if version < 2 else 4)):
        item_id = read(2 if version < 2 else 4)
        construction_method = read(2) & 0xF if version in (1, 2) else 0
        read(2)  # The data reference index
        base_offset = read(base_offset_size)
        extents = []
        for _ in range(read(2)):
            read(index_size)
            extents.append((base_offset + read(offset_size), read(length_size)))
        if item_id == wanted_id:
            return extents if construction_method == 0 else []
    return []


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
