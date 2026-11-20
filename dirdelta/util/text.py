"""Small texts said everywhere, said one way: counts of files, lists cut short, sizes and durations"""


def counted(count, noun):
    """'1 error', or 'N errors': count of noun, in the plural unless it's one"""
    return "%d %s%s" % (count, noun, "" if count == 1 else "s")


def files(count, grouped=False):
    """'1 file', or 'N files' (with grouped, N with thousands separators: '17,427 files')"""
    if count == 1:
        return "1 file"
    return ("{:,} files" if grouped else "{} files").format(count)


# How many of a list's lines a screen shows, at most (see listed())
MAX_LISTED = 10


def listed(lines, most=MAX_LISTED, indent='  '):
    """The first most of lines (e.g. one a file), then '(and N more)' for the rest, if any, after
    indent"""
    lines = list(lines)
    return lines[:most] + (["%s(and %d more)" % (indent, len(lines) - most)] if len(lines) > most else [])


def format_size(size):
    """A size in bytes for people: 512 B, 3.4 KB, 1.2 MB, ..."""
    if size < 1024:
        return "%d B" % (size,)
    size /= 1024.0
    for unit in ("KB", "MB"):
        if size < 1024:
            return "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%.1f GB" % (size,)


def format_duration(seconds):
    """A duration for people: 45 s, 12 min, 3 h 20 min"""
    seconds = int(seconds)
    if seconds < 60:
        return "%d s" % (seconds,)
    if seconds < 3600:
        return "%d min" % (seconds // 60,)
    return "%d h %d min" % (seconds // 3600, seconds % 3600 // 60)


# The units an age is said in (see format_age()), each with how many seconds it is
AGE_UNITS = (('year', 365 * 86400), ('month', 30 * 86400), ('week', 7 * 86400), ('day', 86400),
             ('hour', 3600), ('minute', 60))


def format_age(seconds):
    """How long ago, for people, in its largest whole unit: 'just now' (under a minute), '3 minutes
    ago', '1 day ago', '6 months ago', '2 years ago'"""
    for unit, length in AGE_UNITS:
        if seconds >= length:
            return "%s ago" % (counted(int(seconds // length), unit),)
    return "just now"
