"""Where the other replica has a file of the same name as one it lacks, shown beside the file picker
(picker.pick_files()'s previews), and offered for Rename: the diff is by path only, so a file moved
(or a dir renamed) in one replica is missing from the other, and the user can tell such a file from
one that's really missing before acting on it.

A match is likelier the more of these it has: the same size, the same date taken (photos), and the
file's siblings (the other missing files of its dir, a few of them tried) in its dir too, as when a
dir was moved or renamed; and then the closer its size is."""
import collections
import os
import time

# How many of a name's files in the other replica a preview lists (a common name, like README.md,
# may have many): the likeliest to be the file
MAX_MATCHES = 10
# How often what's found so far is sent to the picker, with how far it's got, in seconds
SEND_INTERVAL = 0.1
# How many of a file's siblings are looked for in a match's dir: a few say enough
SIBLINGS_TRIED = 10

# A file of the same name in the other replica: its relpath, size and date taken (or None), and how
# many of the file's siblings (of how many tried) are in its dir too
Match = collections.namedtuple('Match', ['relpath', 'size', 'date_taken', 'siblings_found',
                                         'siblings_tried'])


class Index(object):
    """A replica's files by name, built once (in the background, by find_previews(), or by
    sure_matches()), and then kept up to date as files are copied into the replica, removed from it
    or moved in it (add(), remove(), move()), rather than built again; or built again after the
    replica is read anew (invalidate())."""

    def __init__(self, replica):
        self.replica = replica
        # {name: {relpath: size}}, and the names in each dir, once built
        self._by_name = None
        self._names_by_dir = None
        # Dates taken read so far, by relpath
        self._dates_taken = {}

    def is_built(self):
        return self._by_name is not None

    def build(self, progress=None):
        """Build it, unless it is: from the replica's files_by_name(progress), which may raise to
        stop it (and then it isn't built)"""
        if self.is_built():
            return
        by_name = {name: dict(files) for name, files in self.replica.files_by_name(progress).items()}
        names_by_dir = collections.defaultdict(set)
        for name, files in by_name.items():
            for relpath in files:
                names_by_dir[os.path.dirname(relpath)].add(name)
        self._by_name, self._names_by_dir = by_name, names_by_dir

    def invalidate(self):
        self._by_name = self._names_by_dir = None
        self._dates_taken = {}

    def files_named(self, name):
        """{relpath: size} of the files with the name"""
        return self._by_name.get(name, {})

    def names_in(self, dirpath):
        return self._names_by_dir.get(dirpath, set())

    def date_taken(self, relpath):
        if relpath not in self._dates_taken:
            self._dates_taken[relpath] = self.replica.date_taken(relpath)
        return self._dates_taken[relpath]

    def add(self, relpath, size):
        """A file is at relpath now (unless it isn't built yet, when there's nothing to change)"""
        if self.is_built():
            name = os.path.basename(relpath)
            self._by_name.setdefault(name, {})[relpath] = size
            self._names_by_dir[os.path.dirname(relpath)].add(name)

    def remove(self, relpath):
        if self.is_built():
            name = os.path.basename(relpath)
            files = self._by_name.get(name, {})
            files.pop(relpath, None)
            if not files:
                self._by_name.pop(name, None)
            self._names_by_dir.get(os.path.dirname(relpath), set()).discard(name)
        self._dates_taken.pop(relpath, None)

    def move(self, relpath, new_relpath):
        if self.is_built():
            size = self.files_named(os.path.basename(relpath)).get(relpath)
            self.remove(relpath)
            self.add(new_relpath, size)


class _Matcher(object):
    """Finds the matches of src's missing files at relpaths in the other replica's index"""

    def __init__(self, relpaths, src, index):
        self._src = src
        self._index = index
        # A few of each dir's missing files' names, to look for in a match's dir (one more than
        # tried, as the file itself is one of them)
        self._siblings = collections.defaultdict(list)
        for relpath in relpaths:
            dirpath, name = os.path.split(relpath)
            if len(self._siblings[dirpath]) <= SIBLINGS_TRIED:
                self._siblings[dirpath].append(name)
        # Which of a dir's siblings are in another dir, by (its dir, the other dir): the same for
        # all its files
        self._siblings_in = {}
        # src's dates taken read so far, by relpath
        self._dates_taken = {}

    def date_taken(self, relpath):
        """src's file's date taken (read once)"""
        if relpath not in self._dates_taken:
            self._dates_taken[relpath] = self._src.date_taken(relpath)
        return self._dates_taken[relpath]

    def matches(self, relpath):
        """The file's matches (Match), the likeliest first"""
        dirpath, name = os.path.split(relpath)
        files = self._index.files_named(name)
        if not files:
            return []
        size, date = self._src.file_size(relpath), self.date_taken(relpath)
        tried = [sibling for sibling in self._siblings[dirpath] if sibling != name][:SIBLINGS_TRIED]
        found = []
        for match_relpath, match_size in files.items():
            match_dir = os.path.dirname(match_relpath)
            key = (dirpath, match_dir)
            if key not in self._siblings_in:
                self._siblings_in[key] = set(self._siblings[dirpath]) & self._index.names_in(match_dir)
            nr_found = sum(1 for sibling in tried if sibling in self._siblings_in[key])
            found.append(Match(match_relpath, match_size, self._index.date_taken(match_relpath),
                               nr_found, len(tried)))
        return sorted(found, key=lambda match: _unlikeliness(match, size, date))


def _unlikeliness(match, size, date):
    """What sorts a match after the likelier ones (see the module's doc), then by path"""
    is_size_known = size is not None and match.size is not None
    return (not (is_size_known and match.size == size),
            not (date is not None and match.date_taken == date),
            -(match.siblings_found / match.siblings_tried if match.siblings_tried else 0),
            not is_size_known, abs(match.size - size) if is_size_known else 0,
            match.relpath.split('/'))


def sure_match(matches, size, date):
    """Of a file's matches (likeliest first), the one surely the same file, moved, or None: the only
    one of the same size (and the same date taken, where both are known), or of several, the one
    with more of its siblings than any other"""
    same = [match for match in matches
            if size is not None and match.size == size and
            (date is None or match.date_taken is None or match.date_taken == date)]
    if len(same) == 1:
        return same[0]
    if len(same) > 1 and same[0].siblings_found > max(match.siblings_found for match in same[1:]):
        return same[0]
    return None


def sure_matches(relpaths, src, index):
    """{relpath: the relpath of its sure match (see sure_match())} of src's missing files at relpaths
    that have one in index (built if it isn't)"""
    index.build()
    matcher = _Matcher(relpaths, src, index)
    found = {}
    for relpath in relpaths:
        matches = matcher.matches(relpath)
        match = (sure_match(matches, src.file_size(relpath), matcher.date_taken(relpath))
                 if matches else None)
        if match is not None:
            found[relpath] = match.relpath
    return found


def find_previews(relpaths, src, index, send):
    """Find, for each of src's files at relpaths (which the other replica, index's, lacks at those
    paths), where the other replica has files of the same name, and send() them
    (picker.pick_files()'s previews) as they're found (see _preview()). Until a file's are sent, the
    picker shows how far it's got: building the index (if it isn't), then matching. Lets
    picker.PickerClosed go up, once the picker is gone."""
    dst_name = index.replica.displayname()
    title = ["Looking for files of the same", "names in %s..." % (dst_name,)]
    is_due = _Throttle(SEND_INTERVAL)
    send(default=title + ["Listing its files"])
    try:
        index.build(lambda count: is_due() and send(default=title + ["Listed %d of its files" % (count,)]))
        matcher = _Matcher(relpaths, src, index)
        found = {}
        for i, relpath in enumerate(relpaths):
            found[relpath] = _preview(relpath, src, dst_name, matcher)
            if is_due():
                send(found, default=title + ["Matched %d of %d files" % (i + 1, len(relpaths))])
                found = {}
    except (OSError, ValueError) as error:
        send(default=["Couldn't look for files of", "the same names in %s:" % (dst_name,), str(error)])
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


def _preview(relpath, src, dst_name, matcher):
    """The lines about src's file at relpath: its size and date taken, and its matches, the
    likeliest first, each with its dir, size, date taken and siblings found, and which is surely the
    file, if one is; or that there are none"""
    matches = matcher.matches(relpath)
    size = src.file_size(relpath)
    # Read only for a file with matches: it's to compare
    date = matcher.date_taken(relpath) if matches else None
    about = [format_size(size)] if size is not None else []
    if date is not None:
        about.append("taken " + date)
    lines = ["This one: " + ", ".join(about)] if about else []
    if not matches:
        return lines + ["In %s:" % (dst_name,), "  no file of this name"]
    lines.append("In %s, likeliest first:" % (dst_name,))
    sure = sure_match(matches, size, date)
    for match in matches[:MAX_MATCHES]:
        dirpath, name = os.path.split(match.relpath)
        lines += ["  %s/" % (dirpath or '.',), "    %s%s" % (name, _size_note(match.size, size))]
        if match.date_taken is not None:
            lines.append("    taken %s%s" % (match.date_taken,
                                             ", the same" if match.date_taken == date else ""))
        if match.siblings_tried:
            lines.append("    with %d of %d of its dir's files" % (match.siblings_found,
                                                                   match.siblings_tried))
        if match is sure:
            lines.append("    surely this file, moved")
    if len(matches) > MAX_MATCHES:
        lines.append("(and %d more)" % (len(matches) - MAX_MATCHES,))
    return lines


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
