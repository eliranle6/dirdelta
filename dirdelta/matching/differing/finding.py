"""Finding the files two replicas both have at the same path that differ, and which is newer"""
import collections

from dirdelta.trees import paths

# The hash both kinds of replica know: Drive's, which the hash cache keeps too
ALGORITHM = 'sha1'

# Why a file differs: its sizes, or its contents (same size, other hashes)
BY_SIZE = 'size'
BY_CONTENTS = 'contents'

# A file of src's that dst has another version of, at the same path: each side's size and
# modification time (None if it isn't known), and why it differs (BY_SIZE or BY_CONTENTS)
Change = collections.namedtuple('Change', ['src_size', 'dst_size', 'src_mtime', 'dst_mtime', 'by'])


class Changes(dict):
    """find()'s {relpath: Change}, and the files both have of the same size that couldn't be
    compared, a hash being unknown on either side (uncompared: their relpaths, sorted)"""
    def __init__(self, changes=(), uncompared=()):
        super().__init__(changes)
        self.uncompared = list(uncompared)

# How close two modification times are to be the same, in seconds (FAT's are by 2 s)
SAME_TIME = 2


def find(src, dst, compared=None):
    """Changes ({relpath: Change}) of the files both have at the same paths that differ, src's way,
    each dir's together, sorted, and the ones of the same size that couldn't be compared. compared:
    {relpath: (src's size, dst's size, whether they're the same)} of the ones compared on request
    (see sync/comparing.py), which settle those, while their sizes are still the same. Lists both
    (a local one by one find and one query of the hash cache), so it can take a moment: shows
    nothing, so it can run in the background."""
    compared = compared or {}
    src_files = src.listed(ALGORITHM)
    dst_files = dst.listed(ALGORITHM)
    found = {}
    uncompared = []
    for relpath, (size, hash_) in src_files.items():
        other = dst_files.get(relpath)
        if other is None or paths.is_meta(relpath):
            continue
        other_size, other_hash = other
        if size is None or other_size is None:
            # e.g. Google's own files, which have none
            continue
        if size != other_size:
            by = BY_SIZE
        elif hash_ and other_hash:
            if hash_ == other_hash:
                continue
            by = BY_CONTENTS
        elif compared.get(relpath, (None, None, None))[:2] == (size, other_size):
            if compared[relpath][2]:
                continue
            by = BY_CONTENTS
        else:
            uncompared.append(relpath)
            continue
        found[relpath] = by
    in_order = lambda relpaths: sorted(relpaths, key=lambda relpath: relpath.split('/'))
    return Changes(((relpath, Change(src_files[relpath][0], dst_files[relpath][0], src.modified_time(relpath),
                                     dst.modified_time(relpath), found[relpath]))
                    for relpath in in_order(found)), in_order(uncompared))


def flipped(changes):
    """changes (find()'s) the other way: dst's files that src has another version of"""
    return Changes(((relpath, Change(change.dst_size, change.src_size, change.dst_mtime, change.src_mtime, change.by))
                    for relpath, change in changes.items()), getattr(changes, 'uncompared', ()))


def newer(change):
    """1 if src's version is newer, -1 if dst's is, 0 if they're as new (or it isn't known)"""
    if change.src_mtime is None or change.dst_mtime is None or abs(change.src_mtime - change.dst_mtime) <= SAME_TIME:
        return 0
    return 1 if change.src_mtime > change.dst_mtime else -1
