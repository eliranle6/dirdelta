"""An imported file's thumbnail for the import's page (jpeg()): a JPEG, made by the pickers' pictures'
code (ui/images.py: photos, HEIF, a video's frame by ffmpeg), kept in the import's folder"""
import io
import os

from dirdelta.ui import images

try:
    from PIL import Image
except ImportError:
    Image = None

SIZE = 360
THUMBS_DIR = 'thumbs'


def jpeg(found, relpath):
    """The JPEG of the import found's file at relpath, or None if it has none (not copied yet, or no
    picture)"""
    path = os.path.join(found.folder, THUMBS_DIR, relpath + '.jpg')
    try:
        with open(path, 'rb') as kept:
            return kept.read()
    except OSError:
        pass
    encoded = images.of_local_file(found.local_path(relpath), SIZE, SIZE) if Image is not None else None
    if not encoded:
        return None
    width, height, pixels = encoded.split(' ', 2)
    image = Image.frombytes('RGB', (int(width), int(height)), bytes.fromhex(pixels))
    data = io.BytesIO()
    image.save(data, 'JPEG', quality=80)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as kept:
        kept.write(data.getvalue())
    return data.getvalue()
