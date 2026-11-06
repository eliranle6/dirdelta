"""The files read, by extension, how much of each, and the EXIF tags and markers looked for"""


# The extensions of the files read (others aren't, to save reading them)
JPEG_EXTENSIONS = ('.jpg', '.jpeg', '.jpe')
HEIF_EXTENSIONS = ('.heic', '.heif')
CR3_EXTENSIONS = ('.cr3',)
RAF_EXTENSIONS = ('.raf',)
# Raw photos that are TIFF files (with their own magic numbers, some: ORF's, RW2's), and TIFFs
TIFF_EXTENSIONS = ('.cr2', '.nef', '.nrw', '.arw', '.srf', '.sr2', '.dng', '.orf', '.rw2', '.pef',
                   '.srw', '.3fr', '.erf', '.kdc', '.mef', '.mos', '.iiq', '.tif', '.tiff')
# How much of a TIFF file's start is read: its IFD0 and EXIF IFD are near it
MAX_TIFF_HEADER = 1 << 20
# The most of a HEIF file's EXIF item read
MAX_EXIF_SIZE = 1 << 20
# EXIF tags: the IFD of the EXIF ones, and the dates in it (and IFD0's, a fallback)
EXIF_IFD_TAG = 0x8769
DATE_TIME_ORIGINAL_TAG = 0x9003
DATE_TIME_TAG = 0x0132
# A JPEG segment marker without a length after it
STANDALONE_MARKERS = set(range(0xD0, 0xDA)) | {0x01}
# The uuid box in a CR3's moov box that holds its metadata (CMT1: IFD0, CMT2: the EXIF IFD, as TIFFs)
CANON_UUID = bytes.fromhex('85c0b687820f11e08111f4ce462b6a48')
# A RAF's start, and where in it its embedded JPEG's offset is (then its length), big-endian
RAF_MAGIC = b'FUJIFILMCCD-RAW '
RAF_JPEG_OFFSET = 84
