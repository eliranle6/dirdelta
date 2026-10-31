"""Small texts said everywhere, said one way: counts of files"""


def files(count, grouped=False):
    """'1 file', or 'N files' (with grouped, N with thousands separators: '17,427 files')"""
    if count == 1:
        return "1 file"
    return ("{:,} files" if grouped else "{} files").format(count)
