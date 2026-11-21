"""The selected file's picture, in a file picker's preview column (picker.pick_files(images=...)): a
photo or another image (by Pillow, if it's installed), a PDF's first page (by pdftoppm, if it's
there), a video's frame (by ffmpeg, if it's there), or a Drive file's thumbnail (Drive makes them for images, videos, PDFs and Google's files).
treepicker draws it with half blocks, two pixels a character, in 256 colors, below the column's text
(see its --preview's \\x03), so it's made here only as big as the column can show."""
import io
import os
import shutil
import subprocess
import tempfile

try:
    from PIL import ExifTags, Image, ImageOps
except ImportError:  # Without Pillow, no pictures (the rest is the same)
    ExifTags = Image = ImageOps = None

from dirdelta.util import media

# Files bigger than this aren't read for their picture (it would take too long for a preview)
MAX_FILE_BYTES = 200 * 1024 ** 2
PDF_EXTENSIONS = ('.pdf',)
# How long pdftoppm may take for a page, and ffmpeg for a video's frame, in seconds
PDF_TIMEOUT = 10
VIDEO_TIMEOUT = 10
# Where in a video its frame is taken from, in seconds (its very first is often black, a fade in),
# or its first, if it's shorter
VIDEO_FRAME_AT = 1
# What Pillow opens, by extension (it reads others too, but these are the ones worth trying by name),
# and HEIF's if pillow-heif is installed
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.jpe', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.ico',
                    '.ppm', '.pgm', '.pbm', '.tga', '.jfif')
HEIF_EXTENSIONS = ('.heic', '.heif')
# A photo's EXIF thumbnail (see exif_thumbnail()): where its JPEG is (IFD1's tags), what's before the TIFF
# data in Pillow's info['exif'], the photo's orientation tag and the ones that turn it a quarter, and how far
# the thumbnail's shape may be from the photo's (a 4:3 one of a 3:2 photo has bars)
JPEG_OFFSET, JPEG_LENGTH = 0x0201, 0x0202
EXIF_HEADER = b'Exif\x00\x00'
ORIENTATION = 0x0112
TURNED_SIDEWAYS = (5, 6, 7, 8)
SHAPE_TOLERANCE = 0.02

_heif_checked = False


def is_available():
    """Whether pictures can be shown at all (Pillow is installed)"""
    return Image is not None


def _heif_opener():
    """Whether Pillow can open HEIF files (pillow-heif, registered once)"""
    global _heif_checked, HEIF_EXTENSIONS
    if not _heif_checked:
        _heif_checked = True
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            HEIF_EXTENSIONS = ()
    return bool(HEIF_EXTENSIONS)


def has_picture(name):
    """Whether a file of this name may have a picture to show, by its extension"""
    extension = os.path.splitext(name)[1].lower()
    return (extension in IMAGE_EXTENSIONS or extension in PDF_EXTENSIONS or
            (extension in HEIF_EXTENSIONS and _heif_opener()) or
            (extension in media.VIDEO_EXTENSIONS and shutil.which('ffmpeg') is not None))


def encoded(image, max_width, max_height):
    """treepicker's image (see its --preview): image (a Pillow image), made to fit in max_width x
    max_height pixels, as its width, its height and its pixels in hex"""
    image = ImageOps.exif_transpose(image)
    if image.mode != 'RGB':
        # Transparency on black, as a terminal's background mostly is
        image = image.convert('RGBA')
        background = Image.new('RGBA', image.size, (0, 0, 0, 255))
        image = Image.alpha_composite(background, image).convert('RGB')
    image.thumbnail((max_width, max_height))
    return '%d %d %s' % (image.width, image.height, image.tobytes().hex())


def of_local_file(path, max_width, max_height):
    """treepicker's image of the local file at path (see encoded()), or None if it has none, or it
    can't be read"""
    if not is_available() or not has_picture(path):
        return None
    try:
        if media.is_video(path):
            # Not read whole: ffmpeg seeks to its frame
            return _of_video(path, max_width, max_height)
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        if path.lower().endswith(PDF_EXTENSIONS):
            return _of_pdf(path, max_width, max_height)
        with Image.open(path) as image:
            # The photo's own thumbnail, if it's big enough: nothing decoded, and only its start read
            embedded = exif_thumbnail(image, max_width, max_height)
            if embedded is not None:
                return encoded(embedded, max_width, max_height)
            # A JPEG decoded at a fraction of its size, which is much faster for a photo
            image.draft('RGB', (max_width, max_height))
            return encoded(image, max_width, max_height)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def exif_thumbnail(image, max_width, max_height):
    """The thumbnail a photo carries in its EXIF (a camera's or a phone's: 160x120, or a Pixel's 510x384), if
    it's as big as the photo would be made to fit in max_width x max_height and of the photo's shape (not one
    with bars), turned as the photo is; else None"""
    try:
        exif = image.getexif()
        thumbnail = exif.get_ifd(ExifTags.IFD.IFD1)
        offset, length = thumbnail.get(JPEG_OFFSET), thumbnail.get(JPEG_LENGTH)
        raw = image.info.get('exif')
        if not offset or not length or not raw:
            return None
        # (raw is its APP1's: 'Exif\0\0' before the TIFF data the offset is in)
        start = len(EXIF_HEADER) if raw.startswith(EXIF_HEADER) else 0
        embedded = Image.open(io.BytesIO(raw[start + offset:start + offset + length]))
        embedded.load()
    except (OSError, ValueError, SyntaxError, KeyError, TypeError):
        return None
    width, height = image.size
    if abs(embedded.width / embedded.height - width / height) > SHAPE_TOLERANCE * width / height:
        return None
    # The size it'd be shown at (as Image.thumbnail() makes it, before it's turned: the box turned instead)
    orientation = exif.get(ORIENTATION, 1)
    box = (max_height, max_width) if orientation in TURNED_SIDEWAYS else (max_width, max_height)
    scale = min(1, box[0] / width, box[1] / height)
    if embedded.width + 1 < width * scale or embedded.height + 1 < height * scale:
        return None
    # (It has no EXIF of its own: the photo's orientation is given to it, for encoded()'s exif_transpose())
    embedded.getexif()[ORIENTATION] = orientation
    return embedded


def _of_pdf(path, max_width, max_height):
    """The image of a PDF's first page, by pdftoppm, or None"""
    pdftoppm = shutil.which('pdftoppm')
    if pdftoppm is None:
        return None
    with tempfile.TemporaryDirectory(prefix='dirdelta-page-') as dirpath:
        prefix = os.path.join(dirpath, 'page')
        try:
            subprocess.run([pdftoppm, '-png', '-f', '1', '-l', '1', '-singlefile',
                            '-scale-to', str(max(max_width, max_height)), path, prefix],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=PDF_TIMEOUT, check=True)
        except (subprocess.SubprocessError, OSError):
            return None
        with Image.open(prefix + '.png') as image:
            return encoded(image, max_width, max_height)


def _of_video(path, max_width, max_height):
    """The image of a video's frame (at VIDEO_FRAME_AT, or its first), by ffmpeg, or None"""
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        return None
    for at in (VIDEO_FRAME_AT, 0):
        try:
            # Seeking before the input is to the nearest keyframe, without decoding up to it
            done = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-ss', str(at), '-i', path, '-frames:v', '1',
                                   '-vf', 'scale=%d:%d:force_original_aspect_ratio=decrease' % (max_width, max_height),
                                   '-f', 'image2pipe', '-c:v', 'png', '-'],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=VIDEO_TIMEOUT)
        except (subprocess.SubprocessError, OSError):
            return None
        if done.stdout:
            return of_data(done.stdout, max_width, max_height)
    return None


def to_jpeg(image, quality=80):
    """A JPEG's bytes of image (as encoded() makes it), or None if it's None"""
    if image is None or Image is None:
        return None
    width, height, pixels = image.split(' ', 2)
    data = io.BytesIO()
    Image.frombytes('RGB', (int(width), int(height)), bytes.fromhex(pixels)).save(data, 'JPEG', quality=quality)
    return data.getvalue()


def of_data(data, max_width, max_height):
    """treepicker's image of an image file's contents (bytes, e.g. a thumbnail), or None"""
    if not is_available() or not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            return encoded(image, max_width, max_height)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def of_replica(tree):
    """A picker.pick_files() images function for the files of tree (a local replica's, or Drive's):
    each file's picture, from the file itself, or Drive's thumbnail of it. None without Pillow."""
    if not is_available():
        return None
    from dirdelta.trees import localdiskdirtree
    if localdiskdirtree.is_local(tree):
        return lambda relpath, max_width, max_height: of_local_file(
            os.path.join(tree.fullpath(), relpath), max_width, max_height)
    if hasattr(tree, 'thumbnail'):
        return lambda relpath, max_width, max_height: of_data(
            tree.thumbnail(relpath, max(max_width, max_height)), max_width, max_height)
    return None
