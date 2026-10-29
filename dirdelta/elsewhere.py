"""Where the other replica has a file of the same name as one it lacks, shown beside the file picker
(picker.pick_files()'s previews): the diff is by path only, so a file moved (or a dir renamed) in
one replica is missing from the other, and the user can tell such a file from one that's really
missing before copying or removing it."""
import os
import time

# How many of a name's files in the other replica a preview lists (a common name, like README.md,
# may have many): the likeliest to be the file
MAX_MATCHES = 10
# How often what's found so far is sent to the picker, with how far it's got, in seconds
SEND_INTERVAL = 0.1


def find_previews(relpaths, src, dst, send):
    """Find, for each of src's files at relpaths (which dst lacks at those paths), where dst has
    files of the same name, and send() them (picker.pick_files()'s previews) as they're found:
    their dirs and sizes, the likeliest to be the file first (see _preview()), or that dst has
    none. Until a file's are sent, the picker shows how far it's got. Lets picker.PickerClosed
    go up, once the picker is gone."""
    title = ["Looking for files of the same", "names in %s..." % (dst.displayname(),)]
    is_due = _Throttle(SEND_INTERVAL)
    send(default=title + ["Listing its files"])
    try:
        by_name = dst.files_by_name(
            lambda count: is_due() and send(default=title + ["Listed %d of its files" % (count,)]))
        found = {}
        for i, relpath in enumerate(relpaths):
            found[relpath] = _preview(src.file_size(relpath), dst.displayname(),
                                      by_name.get(os.path.basename(relpath), []))
            if is_due():
                send(found, default=title + ["Matched %d of %d files" % (i + 1, len(relpaths))])
                found = {}
    except (OSError, ValueError) as error:
        send(default=["Couldn't look for files of", "the same names in %s:" % (dst.displayname(),),
                      str(error)])
        return
    # Dirs show nothing
    send(found, default=[])


class _Throttle(object):
    """Called, says whether interval seconds passed since it last said so (the first call too)"""
    def __init__(self, interval):
        self._interval = interval
        self._last = None

    def __call__(self):
        now = time.monotonic()
        if self._last is not None and now - self._last < self._interval:
            return False
        self._last = now
        return True


def _preview(size, dst_name, matches):
    """The lines about a file of the given size (or None), given its name's matches in dst
    ([(relpath, size)]): each one's dir and size, the likeliest first: the same size, then the
    closest in size, then the ones whose size isn't known"""
    lines = ["This one: %s" % (format_size(size),)] if size is not None else []
    if not matches:
        return lines + ["In %s:" % (dst_name,), "  no file of this name"]
    lines.append("In %s, likeliest first:" % (dst_name,))
    matches = sorted(matches, key=lambda match: _unlikeliness(match, size))
    for match_relpath, match_size in matches[:MAX_MATCHES]:
        dirpath, name = os.path.split(match_relpath)
        lines += ["  %s/" % (dirpath or '.',), "    %s%s" % (name, _size_note(match_size, size))]
    if len(matches) > MAX_MATCHES:
        lines.append("(and %d more)" % (len(matches) - MAX_MATCHES,))
    return lines


def _unlikeliness(match, size):
    """What sorts a match (relpath, size) after the likelier ones: the difference of its size from
    size, unknown sizes last, then its path"""
    match_relpath, match_size = match
    is_unknown = size is None or match_size is None
    return (is_unknown, 0 if is_unknown else abs(match_size - size), match_relpath.split('/'))


def _size_note(match_size, size):
    if match_size is None:
        return ""
    if match_size == size:
        return "  %s, same size" % (format_size(match_size),)
    if size is not None and format_size(match_size) == format_size(size):
        # Not to look the same as this one's
        return "  %d B" % (match_size,)
    return "  " + format_size(match_size)


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
