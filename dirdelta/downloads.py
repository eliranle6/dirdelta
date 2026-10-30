"""Drive files downloaded to be read on this machine: by Claude, describing them, or by the user,
opening one (inbox.py). Kept in DOWNLOADS_DIR, so each is downloaded once: in a dir of its own
(named by the file's cloud path and size, so a changed file is downloaded anew), under its own name,
so it's opened by its type, and Claude, which is let read the dirs of the files it's given, reads
only it. The least recently used go once they take more than MAX_BYTES."""
import hashlib
import os
import shutil

DOWNLOADS_DIR = os.path.expanduser('~/.cache/dirdelta/downloads')
MAX_BYTES = 2 * 1024 ** 3


def get(cloud_path, size, fetch):
    """The local path of the Drive file at cloud_path (of size), downloaded with fetch(local_path)
    unless it was already. Raises what fetch raises (and then keeps nothing)."""
    key = hashlib.sha1(('%s\t%s' % (cloud_path, size)).encode('utf-8', 'surrogateescape')).hexdigest()[:16]
    path = os.path.join(DOWNLOADS_DIR, key, os.path.basename(cloud_path))
    if os.path.exists(path):
        # Used now: the last to go
        os.utime(os.path.dirname(path))
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial = path + '.part'
    try:
        fetch(partial)
        os.replace(partial, path)
    except BaseException:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        raise
    _prune(keep=os.path.dirname(path))
    return path


def _prune(keep):
    """Remove the least recently used downloads (but keep's) until they take MAX_BYTES at most"""
    found = []
    for entry in os.scandir(DOWNLOADS_DIR):
        if entry.is_dir(follow_symlinks=False):
            size = sum(os.path.getsize(os.path.join(entry.path, name)) for name in os.listdir(entry.path))
            found.append((entry.stat().st_mtime, entry.path, size))
    total = sum(size for _, _, size in found)
    for _, path, size in sorted(found):
        if total <= MAX_BYTES:
            return
        if path != keep:
            shutil.rmtree(path, ignore_errors=True)
            total -= size
