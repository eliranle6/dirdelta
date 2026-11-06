"""When a photo was taken, from its EXIF data (DateTimeOriginal), read from a JPEG's header, a HEIF
(HEIC) file's EXIF item, a TIFF-based raw photo's (CR2, NEF, ARW, DNG, ...) IFDs, a Canon CR3's
CMT boxes or a Fujifilm RAF's embedded JPEG: enough to tell two photos of the same name apart,
without a library for it.

Its parts are in the modules here."""
from dirdelta.util.exif.dates import date_taken  # noqa: F401
from dirdelta.util.exif.tiff import normalized  # noqa: F401
