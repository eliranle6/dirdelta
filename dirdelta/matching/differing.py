"""The files that two replicas both have at the same path, but not alike: of other sizes, or of the
same size with other contents by hashes known without reading the files (the hash cache's for a
local one, Drive's for Drive's; see docs/plans.md, plan A). The same size with a hash unknown on
either side isn't counted, so there are no false alarms. Modification times say only which one is
newer, never whether they differ (copies made before 2026-10-29 have their copy's time).

They're shown in the same pickers as the files only one has (interactive_dir_sync), with a tag: in
each way's, as either side can win, and Copy replaces the other side's version (to the trash)."""
import collections
import time

from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.util import text

# The hash both kinds of replica know: Drive's, which the hash cache keeps too
ALGORITHM = 'sha1'

# Why a file differs: its sizes, or its contents (same size, other hashes)
BY_SIZE = 'size'
BY_CONTENTS = 'contents'

# A file of src's that dst has another version of, at the same path: each side's size and
# modification time (None if it isn't known), and why it differs (BY_SIZE or BY_CONTENTS)
Change = collections.namedtuple('Change', ['src_size', 'dst_size', 'src_mtime', 'dst_mtime', 'by'])

# The tags' marks, by which side is newer (by modification time): '>' this one, '<' the other one,
# and '≠' when the times don't say. A search finds them by it (e.g. /< for the ones older here).
MARK = '≠'
NEWER_MARK = '>'
OLDER_MARK = '<'
# The tags' styles (see picker.styled()), by which side is newer: newer here in Copy's blue (copying
# from here is likely right), older here in red (Copy would replace a newer version), and in yellow
# when the times don't say. Not green (hashed, and hashing done) nor orange (progress).
STYLE = 'yellow'
NEWER_STYLE = 'blue'
OLDER_STYLE = 'red'

# How close two modification times are to be the same, in seconds (FAT's are by 2 s)
SAME_TIME = 2


def find(src, dst):
    """{relpath: Change} of the files both have at the same paths that differ, src's way, each
    dir's together, sorted. Lists both (a local one by one find and one query of the hash cache),
    so it can take a moment: shows nothing, so it can run in the background."""
    src_files = src.listed(ALGORITHM)
    dst_files = dst.listed(ALGORITHM)
    found = {}
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
        elif hash_ and other_hash and hash_ != other_hash:
            by = BY_CONTENTS
        else:
            continue
        found[relpath] = by
    return {relpath: Change(src_files[relpath][0], dst_files[relpath][0], src.modified_time(relpath),
                            dst.modified_time(relpath), found[relpath])
            for relpath in sorted(found, key=lambda relpath: relpath.split('/'))}


def flipped(changes):
    """changes (find()'s) the other way: dst's files that src has another version of"""
    return {relpath: Change(change.dst_size, change.src_size, change.dst_mtime, change.src_mtime, change.by)
            for relpath, change in changes.items()}


def newer(change):
    """1 if src's version is newer, -1 if dst's is, 0 if they're as new (or it isn't known)"""
    if change.src_mtime is None or change.dst_mtime is None or abs(change.src_mtime - change.dst_mtime) <= SAME_TIME:
        return 0
    return 1 if change.src_mtime > change.dst_mtime else -1


def mark(change):
    """The tag's mark (see NEWER_MARK), by which side is newer"""
    return {1: NEWER_MARK, -1: OLDER_MARK, 0: MARK}[newer(change)]


def tag(change):
    """The tag after a changed file's name in src's picker: '[> newer here, 2.1 MB vs 1.9 MB]',
    '[< older here, same size, other contents]', or '[≠ 3 B vs 4 B]' when the times don't say"""
    parts = [{1: "newer here", -1: "older here", 0: ""}[newer(change)]]
    if change.by == BY_SIZE:
        parts.append("%s vs %s" % _sizes(change.src_size, change.dst_size))
    else:
        parts.append("same size, other contents")
    return "[%s %s]" % (mark(change), ", ".join(part for part in parts if part))


def style(change):
    """The tag's style, by which side is newer"""
    return {1: NEWER_STYLE, -1: OLDER_STYLE, 0: STYLE}[newer(change)]


def styled_tag(change):
    """tag(), styled (style()), after two spaces, to follow a name (see picker.styled())"""
    return picker.styled([("  ", None), (tag(change), style(change))])


def preview_lines(change, dst_name, can_replace=True):
    """A changed file's preview: both versions (size, modification time, which is newer), and what
    Copy does with it"""
    lines = [picker.styled([("%s Another version is in %s" % (mark(change), dst_name), 'bold,' + style(change))])]
    newer_side = newer(change)
    src_size, dst_size = _sizes(change.src_size, change.dst_size)
    for title, size, mtime, is_newer in (("Here:  ", src_size, change.src_mtime, newer_side > 0),
                                         ("There: ", dst_size, change.dst_mtime, newer_side < 0)):
        about = [size] + (["modified " + format_time(mtime)] if mtime is not None else [])
        lines.append(picker.styled([(title, 'bold'), (", ".join(about), None),
                                    (" (newer)" if is_newer else "", NEWER_STYLE)]))
    if change.by == BY_CONTENTS:
        lines.append("Same size, other contents (by their hashes)")
    lines.append("")
    if can_replace:
        lines += ["Copy replaces the one there", "(%s)." % ("it goes to the trash" if not paths.is_cloud_path(dst_name)
                                                       else "Drive keeps it as an older version",)]
    lines += ["Remove removes this one only."]
    return lines


def format_time(timestamp):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))


def _sizes(size, other_size):
    """The two sizes for people, in bytes if they'd look the same otherwise"""
    shown, other_shown = text.format_size(size), text.format_size(other_size)
    if shown == other_shown and size != other_size:
        return "%d B" % (size,), "%d B" % (other_size,)
    return shown, other_shown
