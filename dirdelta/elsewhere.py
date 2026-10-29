"""Where the other replica has a file of the same name as one it lacks, shown beside the file picker
(picker.pick_files()'s previews), and offered for Rename: the diff is by path only, so a file moved
(or a dir renamed) in one replica is missing from the other, and the user can tell such a file from
one that's really missing before acting on it.

A match is likelier the more of these it has: the same size, the same date taken (photos), and the
file's siblings (the other missing files of its dir, a few of them tried) in its dir too, as when a
dir was moved or renamed; and then the closer its size is. For the selected file, the same-sized
ones' contents are compared too (check_contents()): one with the same contents is surely it, and the
others are dropped."""
import collections
import os
import time

from dirdelta import dirtree

# How many of a name's files in the other replica a preview lists (a common name, like README.md,
# may have many): the likeliest to be the file
MAX_MATCHES = 10
# How often what's found so far is sent to the picker, with how far it's got, in seconds
SEND_INTERVAL = 0.1
# How many of a file's siblings are looked for in a match's dir: a few say enough
SIBLINGS_TRIED = 10

# A file of the same name in the other replica: its relpath, size and date taken (or None), how
# many of the file's siblings (of how many tried) are in its dir too, and whether its contents are
# the same (None: not compared)
Match = collections.namedtuple('Match', ['relpath', 'size', 'date_taken', 'siblings_found',
                                         'siblings_tried', 'same_contents'])


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
        # Dates taken read so far, and contents' hashes ({algorithm: hex}), by relpath
        self._dates_taken = {}
        self._hashes = {}

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
        self._hashes = {}

    def files_named(self, name):
        """{relpath: size} of the files with the name"""
        return self._by_name.get(name, {})

    def names_in(self, dirpath):
        return self._names_by_dir.get(dirpath, set())

    def date_taken(self, relpath):
        if relpath not in self._dates_taken:
            self._dates_taken[relpath] = self.replica.date_taken(relpath)
        return self._dates_taken[relpath]

    def content_hash(self, relpath, algorithm, should_stop=None):
        """The file's contents' hash, as the replica's content_hash() gives it (worked out once)"""
        hashes = self._hashes.setdefault(relpath, {})
        if algorithm not in hashes:
            hashes[algorithm] = self.replica.content_hash(relpath, algorithm, should_stop)
        return hashes[algorithm]

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
        self._hashes.pop(relpath, None)

    def move(self, relpath, new_relpath):
        # The same file, with the same contents
        hashes = self._hashes.get(relpath)
        if self.is_built():
            size = self.files_named(os.path.basename(relpath)).get(relpath)
            self.remove(relpath)
            self.add(new_relpath, size)
        else:
            self.remove(relpath)
        if hashes:
            self._hashes[new_relpath] = hashes


class _Matcher(object):
    """Finds the matches of src's missing files at relpaths in the other replica's index"""

    def __init__(self, relpaths, src, index, checked=None):
        """checked: {relpath: {match relpath: whether its contents are the same}} of the files whose
        contents were compared (check_contents())"""
        self._src = src
        self._index = index
        self._checked = checked if checked is not None else {}
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
        checked = self._checked.get(relpath, {})
        if any(checked.get(match_relpath) for match_relpath in files):
            # The ones with the same contents are it: the others aren't
            files = {match_relpath: size for match_relpath, size in files.items() if checked.get(match_relpath)}
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
                               nr_found, len(tried), checked.get(match_relpath)))
        return sorted(found, key=lambda match: _unlikeliness(match, size, date))


def _unlikeliness(match, size, date):
    """What sorts a match after the likelier ones (see the module's doc), then by path"""
    is_size_known = size is not None and match.size is not None
    return (match.same_contents is not True, match.same_contents is False,
            not (is_size_known and match.size == size),
            not (date is not None and match.date_taken == date),
            -(match.siblings_found / match.siblings_tried if match.siblings_tried else 0),
            not is_size_known, abs(match.size - size) if is_size_known else 0,
            match.relpath.split('/'))


def sure_match(matches, size, date):
    """Of a file's matches (likeliest first), the one surely the same file, moved, or None: the only
    one of the same size (and the same date taken, where both are known, and not other contents),
    or of several, the one with more of its siblings than any other"""
    same = [match for match in matches
            if size is not None and match.size == size and match.same_contents is not False and
            (date is None or match.date_taken is None or match.date_taken == date)]
    if len(same) == 1:
        return same[0]
    if len(same) > 1 and same[0].siblings_found > max(match.siblings_found for match in same[1:]):
        return same[0]
    return None


def sure_matches(relpaths, src, index, checked=None):
    """{relpath: the relpath of its sure match (see sure_match())} of src's missing files at relpaths
    that have one in index (built if it isn't); checked: as _Matcher's"""
    index.build()
    matcher = _Matcher(relpaths, src, index, checked)
    found = {}
    for relpath in relpaths:
        matches = matcher.matches(relpath)
        match = (sure_match(matches, src.file_size(relpath), matcher.date_taken(relpath))
                 if matches else None)
        if match is not None:
            found[relpath] = match.relpath
    return found


def find_previews(relpaths, src, index, send, checked=None):
    """Find, for each of src's files at relpaths (which the other replica, index's, lacks at those
    paths), where the other replica has files of the same name, and send() them
    (picker.pick_files()'s previews) as they're found (see _preview()). Until a file's are sent, the
    picker shows how far it's got: building the index (if it isn't), then matching. Lets
    picker.PickerClosed go up, once the picker is gone. checked: as _Matcher's."""
    dst_name = index.replica.displayname()
    title = ["Looking for files of the same", "names in %s..." % (dst_name,)]
    is_due = _Throttle(SEND_INTERVAL)
    send(default=title + ["Listing its files"])
    try:
        index.build(lambda count: is_due() and send(default=title + ["Listed %d of its files" % (count,)]))
        matcher = _Matcher(relpaths, src, index, checked)
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


# How often check_contents() looks whether the index is built, while it waits for it, in seconds
INDEX_WAIT_INTERVAL = 0.2


def check_contents(relpaths, src, src_index, index, checked, selection, send):
    """For each of src's missing files at relpaths as it's selected in the picker (selection, a
    picker.Selection), compare its contents with those of its matches of the same size in index
    (once it's built; see _same_contents()), and note which are the same in checked ({relpath:
    {match relpath: whether the same}}, kept by the caller): then its preview (send()) has only the
    ones with the same contents, or says which aren't. Each file once: checked has it then. Reading
    a local file may take a while, so it's stopped when the selection moves on, for the file it's
    on now. Lets picker.PickerClosed go up, once the picker is gone."""
    missing = set(relpaths)
    matcher = None
    dst_name = index.replica.displayname()
    pending = None
    while True:
        if pending is None or not index.is_built():
            moved_to = selection.wait_next(INDEX_WAIT_INTERVAL if pending is not None else None)
            if moved_to is not None:
                pending = moved_to
            continue
        relpath, pending = pending, None
        if relpath not in missing or relpath in checked:
            continue
        size = src.file_size(relpath)
        candidates = [match_relpath for match_relpath, match_size
                      in index.files_named(os.path.basename(relpath)).items()
                      if size is not None and match_size == size]
        if not candidates:
            continue
        matcher = matcher or _Matcher(relpaths, src, index, checked)
        send({relpath: _preview(relpath, src, dst_name, matcher) +
              ["", "Comparing its contents with the", "%s of its size..." % (_files(len(candidates)),)]})
        should_stop = lambda: not selection.is_at(relpath)
        try:
            found = {match_relpath: _same_contents(src, src_index, relpath, index, match_relpath,
                                                   should_stop)
                     for match_relpath in candidates}
        except dirtree.HashStopped:
            # Moved on: its preview as it was, and on to where the selection is now
            send({relpath: _preview(relpath, src, dst_name, matcher)})
            pending = selection.wait_next(0)
            continue
        # Not where it couldn't be told (e.g. a Google file's, which has no hash)
        checked[relpath] = {match_relpath: is_same for match_relpath, is_same in found.items()
                            if is_same is not None}
        send({relpath: _preview(relpath, src, dst_name, matcher)})


# The hashes that Drive gives (drivecache.HASH_FIELDS), the fastest to work out first
_HASH_PREFERENCE = ('sha1', 'sha256')
# How much of each file _same_bytes() reads at a time
COMPARE_READ_SIZE = 1 << 20


def _same_contents(src, src_index, relpath, index, match_relpath, should_stop):
    """Whether src's file at relpath has the same contents as index's at match_relpath, or None if
    it can't be told. Two local files are read side by side, up to where they differ (no hash: it
    would read them all, and the first chunk usually tells); with a Drive file, its hash (the
    fastest that Drive has for it) is compared with the other's (worked out locally, or Drive's
    too), kept in the indexes. Raises dirtree.HashStopped once should_stop() says to."""
    path, match_path = src.local_path(relpath), index.replica.local_path(match_relpath)
    if path is not None and match_path is not None:
        return _same_bytes(path, match_path, should_stop)
    known = set(src.known_hashes(relpath)) | set(index.replica.known_hashes(match_relpath))
    for algorithm in [algorithm for algorithm in _HASH_PREFERENCE if algorithm in known]:
        own = src_index.content_hash(relpath, algorithm, should_stop)
        other = index.content_hash(match_relpath, algorithm, should_stop)
        if own is not None and other is not None:
            return own == other
    return None


def _same_bytes(path, other_path, should_stop):
    """Whether the files at the paths have the same contents, or None if they can't be read"""
    try:
        with open(path, 'rb') as f, open(other_path, 'rb') as other:
            while True:
                if should_stop():
                    raise dirtree.HashStopped()
                chunk = f.read(COMPARE_READ_SIZE)
                if chunk != other.read(COMPARE_READ_SIZE):
                    return False
                if not chunk:
                    return True
    except OSError:
        return None


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
        if match.same_contents is not None:
            lines.append("    the same contents" if match.same_contents else "    other contents")
        if match is sure:
            lines.append("    surely this file, moved")
    if len(matches) > MAX_MATCHES:
        lines.append("(and %d more)" % (len(matches) - MAX_MATCHES,))
    return lines


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


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
