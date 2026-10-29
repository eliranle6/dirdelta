"""Where the other replica has a file of the same name as one it lacks, shown beside the file picker
(picker.pick_files()'s previews): the diff is by path only, so a file moved (or a dir renamed) in
one replica is missing from the other, and the user can tell such a file from one that's really
missing before copying or removing it."""
import os

# How many of a name's files in the other replica a preview lists (a common name, like README.md,
# may have many)
MAX_MATCHES = 10


def previews(relpaths, src, dst):
    """For each of src's files at relpaths (which dst lacks at those paths), the lines that say where
    dst has files of the same name, by relpath: a tree of their paths from dst's root, each with its
    size, said to be the same when it's src's file's; or that dst has none."""
    by_name = dst.files_by_name()
    return {relpath: _preview(src.file_size(relpath), dst.displayname(),
                              by_name.get(os.path.basename(relpath), []))
            for relpath in relpaths}


def _preview(size, dst_name, matches):
    lines = ["In %s:" % (dst_name,)]
    if not matches:
        lines.append("  no file of this name")
    else:
        # The same size first, since those are likely the same file
        matches = sorted(matches, key=lambda match: (size is None or match[1] != size,
                                                     match[0].split('/')))
        shown = sorted(matches[:MAX_MATCHES], key=lambda match: match[0].split('/'))
        lines += _tree_lines([(match_relpath, _size_note(match_size, size))
                              for match_relpath, match_size in shown])
        if len(matches) > MAX_MATCHES:
            lines.append("(and %d more)" % (len(matches) - MAX_MATCHES,))
    if size is not None:
        lines += ["", "This one: %s" % (format_size(size),)]
    return lines


def _size_note(match_size, size):
    if match_size is None:
        return ""
    note = "  " + format_size(match_size)
    if match_size == size:
        note += ", same size"
    return note


def _tree_lines(files):
    """Lines drawing the files (relpath, text to show after the name), sorted by path, as a tree:
    each dir once, above what's in it, indented by its depth"""
    lines = []
    previous_dirs = []
    for relpath, text in files:
        components = relpath.split('/')
        dirs = components[:-1]
        common = 0
        while common < min(len(dirs), len(previous_dirs)) and dirs[common] == previous_dirs[common]:
            common += 1
        for depth in range(common, len(dirs)):
            lines.append("  " * (depth + 1) + dirs[depth] + "/")
        lines.append("  " * (len(dirs) + 1) + components[-1] + text)
        previous_dirs = dirs
    return lines


def format_size(size):
    """A size in bytes for people: 512 B, 3.4 KB, 1.2 MB, ..."""
    if size < 1024:
        return "%d B" % (size,)
    for unit in ("KB", "MB", "GB"):
        size /= 1024.0
        if size < 1024 or unit == "GB":
            break
    return "%.1f %s" % (size, unit)
