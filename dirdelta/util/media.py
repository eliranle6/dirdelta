"""Which files are media (images, audio, video), by their extensions: the least likely to change, the
most likely to be the same file when their names and sizes match, and the biggest, so they're hashed
last (hashing/job.py), or left out"""
import os

from dirdelta.util.exif.formats import (CR3_EXTENSIONS, HEIF_EXTENSIONS, JPEG_EXTENSIONS, RAF_EXTENSIONS,
                                        TIFF_EXTENSIONS)

IMAGE_EXTENSIONS = (JPEG_EXTENSIONS + HEIF_EXTENSIONS + CR3_EXTENSIONS + RAF_EXTENSIONS + TIFF_EXTENSIONS +
                    ('.png', '.gif', '.webp', '.bmp', '.ico', '.ppm', '.pgm', '.pbm', '.tga', '.jfif',
                     '.avif', '.jxl', '.psd', '.xcf', '.crw', '.rw2', '.x3f'))
AUDIO_EXTENSIONS = ('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.oga', '.opus', '.wma', '.aif', '.aiff',
                    '.ape', '.amr', '.mka', '.mid', '.midi')
# Not '.ts' (a TypeScript file more often than an MPEG transport stream)
VIDEO_EXTENSIONS = ('.mp4', '.m4v', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.flv', '.mpg', '.mpeg',
                    '.3gp', '.3g2', '.mts', '.m2ts', '.vob', '.ogv', '.asf', '.divx')
MEDIA_EXTENSIONS = frozenset(IMAGE_EXTENSIONS + AUDIO_EXTENSIONS + VIDEO_EXTENSIONS)


def extension(name):
    return os.path.splitext(name)[1].lower()


def is_media(name):
    """Whether the file named name (or at the path) is an image, audio or a video, by its extension"""
    return extension(name) in MEDIA_EXTENSIONS


def is_video(name):
    return extension(name) in VIDEO_EXTENSIONS
