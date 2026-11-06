"""A HEIF file's EXIF item, and a Canon CR3's CMT boxes: both ISO BMFF boxes"""
import os
import struct

from dirdelta.util.exif.formats import MAX_EXIF_SIZE, MAX_TIFF_HEADER, CANON_UUID


def heif_exif(f):
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


def cr3_tiffs(f):
    """A Canon CR3's TIFFs with dates, the EXIF IFD's (CMT2) first, then IFD0's (CMT1): boxes in
    the moov box's Canon uuid box, each a TIFF of one IFD"""
    end = os.fstat(f.fileno()).st_size
    moov = next(((start, box_end) for kind, start, box_end in _boxes(f, 0, end) if kind == b'moov'), None)
    if moov is None:
        return []
    for kind, start, box_end in _boxes(f, *moov):
        if kind != b'uuid':
            continue
        f.seek(start)
        if f.read(16) != CANON_UUID:
            continue
        found = {child: (child_start, child_end) for child, child_start, child_end in _boxes(f, start + 16, box_end)}
        tiffs = []
        for name in (b'CMT2', b'CMT1'):
            if name in found:
                child_start, child_end = found[name]
                f.seek(child_start)
                tiffs.append(f.read(min(child_end - child_start, MAX_TIFF_HEADER)))
        return tiffs
    return []


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
