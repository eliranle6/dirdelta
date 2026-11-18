"""An imported file's thumbnail for the import's page (jpeg()): a JPEG, made by the pickers' pictures'
code (ui/images.py: photos, HEIF, a video's frame by ffmpeg), kept in the source's pool"""
import io
import os

from dirdelta.ui import images

try:
    from PIL import Image
except ImportError:
    Image = None

SIZE = 360


def jpeg(source_pool, relpath):
    """The JPEG of the file at relpath of source_pool (its copy, or else the phone's), or None if it has
    none (no picture, or not there)"""
    path = source_pool.thumb_path(relpath)
    try:
        with open(path, 'rb') as kept:
            return kept.read()
    except OSError:
        pass
    if Image is None:
        return None
    readable = source_pool.readable_path(relpath)
    if readable is None and source_pool.is_drive:
        # Drive's own thumbnail (it makes them of videos too)
        data = source_pool.tree().thumbnail(relpath, SIZE)
        try:
            image = Image.open(io.BytesIO(data)).convert('RGB') if data else None
        except OSError:
            image = None
    else:
        encoded = images.of_local_file(readable, SIZE, SIZE) if readable else None
        if encoded:
            width, height, pixels = encoded.split(' ', 2)
            image = Image.frombytes('RGB', (int(width), int(height)), bytes.fromhex(pixels))
        else:
            image = None
    if image is None:
        return None
    data = io.BytesIO()
    image.save(data, 'JPEG', quality=80)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as kept:
        kept.write(data.getvalue())
    return data.getvalue()
