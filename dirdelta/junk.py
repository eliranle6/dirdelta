"""Junk an inbox's files may be, by their names and sizes alone (no Claude, nothing read): system
files, temporary and partly downloaded ones, empty ones, and leftovers (installers, and archives
whose contents are beside them). Only offered for removal (see inbox.py), never removed unasked."""
import fnmatch
import posixpath

# (name pattern, why it's junk), matched case-insensitively against a file's name
NAME_RULES = [
    ('thumbs.db', "a Windows thumbnails cache"),
    ('ehthumbs.db', "a Windows thumbnails cache"),
    ('desktop.ini', "a Windows folder's settings"),
    ('.ds_store', "a Mac folder's settings"),
    ('._*', "a Mac file's metadata"),
    ('~$*', "an Office lock file, left by an open document"),
    ('*.tmp', "a temporary file"),
    ('*.temp', "a temporary file"),
    ('*.part', "a partly downloaded file"),
    ('*.partial', "a partly downloaded file"),
    ('*.crdownload', "a partly downloaded file (Chrome)"),
    ('*.download', "a partly downloaded file (Safari)"),
    ('*.exe', "an installer or program"),
    ('*.msi', "an installer"),
    ('*.dmg', "a Mac installer"),
    ('*.pkg', "a Mac installer"),
]
# Archives: junk when what's in them is beside them (a dir of the same name), unpacked already
ARCHIVE_EXTENSIONS = ('.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz')


def find(files, sizes):
    """{relpath: why it's junk} of files (relpaths, '/'-separated) that look like junk by their
    names, sizes ({relpath: size}, None if not known) or what's beside them (the other files)"""
    dirs = {posixpath.dirname(relpath) for relpath in files}
    dirs |= {dirpath for relpath in files for dirpath in _dirs_above(relpath)}
    found = {}
    for relpath in files:
        reason = why(relpath, sizes.get(relpath), dirs)
        if reason is not None:
            found[relpath] = reason
    return found


def why(relpath, size, dirs=()):
    """Why the file at relpath (of size) is junk, or None if it isn't by its name and size; dirs:
    the dirs with files in them, for an archive unpacked beside it"""
    name = posixpath.basename(relpath).lower()
    for pattern, reason in NAME_RULES:
        if fnmatch.fnmatchcase(name, pattern):
            return reason
    for extension in ARCHIVE_EXTENSIONS:
        if name.endswith(extension) and len(name) > len(extension):
            unpacked = posixpath.join(posixpath.dirname(relpath), posixpath.basename(relpath)[:-len(extension)])
            if unpacked in dirs:
                return "an archive whose contents are beside it, in %s/" % (posixpath.basename(unpacked),)
    if size == 0:
        return "an empty file"
    return None


def _dirs_above(relpath):
    dirpath = posixpath.dirname(relpath)
    while dirpath:
        yield dirpath
        dirpath = posixpath.dirname(dirpath)
