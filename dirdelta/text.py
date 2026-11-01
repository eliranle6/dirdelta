"""Small texts said everywhere, said one way: counts of files, and lists cut short"""


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
