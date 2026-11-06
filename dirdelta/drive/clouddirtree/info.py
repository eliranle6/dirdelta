"""What's known of a Drive file, from its metadata"""
import collections

from dirdelta.drive import drivecache


FileInfo = collections.namedtuple('FileInfo', ['size', 'date_taken', 'hashes', 'modified', 'is_google'])
NO_INFO = FileInfo(None, None, {}, None, False)


def info_of(md):
    """The FileInfo of a file's metadata, as Drive gives it"""
    return FileInfo(int(md['size']) if 'size' in md else None, drivecache.date_taken(md), drivecache.hashes(md),
                    drivecache.modified_time(md), drivecache.is_google_file(md))
