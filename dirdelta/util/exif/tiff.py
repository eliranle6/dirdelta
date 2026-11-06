"""The date in TIFF data's IFDs"""
import struct

from dirdelta.util.exif.formats import DATE_TIME_ORIGINAL_TAG, DATE_TIME_TAG, EXIF_IFD_TAG


def normalized(date):
    """An EXIF date ('YYYY:MM:DD HH:MM:SS', as Drive gives it too) as 'YYYY-MM-DD HH:MM:SS', or None
    if it isn't one"""
    date = date.strip().rstrip('\0')
    if len(date) < 19 or date[4] != ':' or date[7] != ':' or not date[:4].isdigit() or date.startswith('0000'):
        return None
    return date[:4] + '-' + date[5:7] + '-' + date[8:19]


def tiff_date(tiff):
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
    if EXIF_IFD_TAG in ifd0:
        exif_ifd = entries(struct.unpack(order + 'I', ifd0[EXIF_IFD_TAG][2])[0])
        if DATE_TIME_ORIGINAL_TAG in exif_ifd:
            date = normalized(text(exif_ifd[DATE_TIME_ORIGINAL_TAG]))
            if date:
                return date
    # A TIFF whose first IFD is the EXIF IFD itself (a CR3's CMT2)
    if DATE_TIME_ORIGINAL_TAG in ifd0:
        date = normalized(text(ifd0[DATE_TIME_ORIGINAL_TAG]))
        if date:
            return date
    if DATE_TIME_TAG in ifd0:
        return normalized(text(ifd0[DATE_TIME_TAG]))
    return None
