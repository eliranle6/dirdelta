"""What's shown of the files that differ: their tags, and their previews"""
import time

from dirdelta.matching.differing.finding import BY_CONTENTS, BY_SIZE, newer
from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.util import text

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
