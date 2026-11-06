"""What's in an archive (a zip, for now), without unpacking it: for exploring one (archive_screen.py),
and telling the AI of it (aiplan.py). It shows nothing."""
import collections
import datetime
import posixpath
import zipfile

from dirdelta.util import text


class ArchiveError(Exception):
    """A file that can't be read as an archive"""


# A file in an archive: its path in it, its size, compressed and not, and when it was last changed
Member = collections.namedtuple('Member', ['relpath', 'size', 'compressed_size', 'modified'])


def is_archive(name):
    """Whether a file's name says it's an archive that can be looked in"""
    return name.lower().endswith('.zip')


def members(path):
    """The files in the archive at the local path (Member), each dir's together, sorted (an archive's
    dirs are shown by what's in them; its odd paths, e.g. /a or ../a, made relative). Raises ArchiveError
    if it can't be read."""
    found = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                relpath = _clean(info.filename)
                if relpath and not info.is_dir():
                    found[relpath] = Member(relpath, info.file_size, info.compress_size, _date(info.date_time))
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError) as error:
        raise ArchiveError("Can't read it as a zip: %s" % (error,))
    return [found[relpath] for relpath in sorted(found, key=lambda relpath: relpath.split('/'))]


def _clean(name):
    parts = [part for part in posixpath.normpath(name.replace('\\', '/')).split('/') if part not in ('', '.', '..')]
    return '/'.join(parts)


def _date(date_time):
    try:
        return datetime.datetime(*date_time)
    except ValueError:
        return None


def said(found, most):
    """What's in an archive (found: Members), in words, its first most files"""
    return "a zip of %s%s: %s" % (text.files(len(found)), " (the first %d)" % (most,) if len(found) > most else "",
                                  ', '.join("%s (%s)" % (member.relpath, text.format_size(member.size))
                                            for member in found[:most]))
