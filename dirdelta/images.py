"""The selected file's picture, in a file picker's preview column (picker.pick_files(images=...)): a
photo or another image (by Pillow, if it's installed), a PDF's first page (by pdftoppm, if it's
there), or a Drive file's thumbnail (Drive makes them for images, videos, PDFs and Google's files).
treepicker draws it with half blocks, two pixels a character, in 256 colors, below the column's text
(see its --preview's \\x03), so it's made here only as big as the column can show."""
import io
import os
import shutil
import subprocess
import tempfile

try:
    from PIL import Image, ImageOps
except ImportError:  # Without Pillow, no pictures (the rest is the same)
    Image = ImageOps = None

# Files bigger than this aren't read for their picture (it would take too long for a preview)
MAX_FILE_BYTES = 200 * 1024 ** 2
PDF_EXTENSIONS = ('.pdf',)
# How long pdftoppm may take for a page, in seconds
PDF_TIMEOUT = 10
# What Pillow opens, by extension (it reads others too, but these are the ones worth trying by name),
# and HEIF's if pillow-heif is installed
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.jpe', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.ico',
                    '.ppm', '.pgm', '.pbm', '.tga', '.jfif')
HEIF_EXTENSIONS = ('.heic', '.heif')

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
            (extension in HEIF_EXTENSIONS and _heif_opener()))


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
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        if path.lower().endswith(PDF_EXTENSIONS):
            return _of_pdf(path, max_width, max_height)
        with Image.open(path) as image:
            # A JPEG decoded at a fraction of its size, which is much faster for a photo
            image.draft('RGB', (max_width, max_height))
            return encoded(image, max_width, max_height)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


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
    from dirdelta import localdiskdirtree
    if localdiskdirtree.is_local(tree):
        return lambda relpath, max_width, max_height: of_local_file(
            os.path.join(tree.fullpath(), relpath), max_width, max_height)
    if hasattr(tree, 'thumbnail'):
        return lambda relpath, max_width, max_height: of_data(
            tree.thumbnail(relpath, max(max_width, max_height)), max_width, max_height)
    return None
