"""Where the other replica has a file that a replica lacks, moved or renamed, shown beside the file
picker (picker.pick_files()'s previews), and offered for Rename: the diff is by path only, so a file
moved (or a dir renamed) in one replica is missing from the other, and the user can tell such a file
from one that's really missing before acting on it.

The candidates are the other replica's files of the same name, and, for a big file, those of its
size with another name (renamed); and when the other replica is Drive's, which knows its files'
hashes, the files of the same contents whatever their name and size (looked up by the file's hash,
when its contents are compared). A candidate is likelier the more of these it has: the same
contents (compared for the selected file, with the same-sized candidates only: check_contents(), or
for all the picked ones before a Rename: check_all()), the same name, the same size, the same date
taken (photos), the file's siblings (the other missing files of its dir, a few of them tried) in its
dir too, as when a dir was moved or renamed, the same modification time; and then the closer its
size is. One with the same contents is surely it, and the others are dropped; one with other
contents never is, and one with another name is dropped then."""
import collections
import os
import time

from dirdelta import dirtree
from dirdelta import picker

# How many of a name's files in the other replica a preview lists (a common name, like README.md,
# may have many): the likeliest to be the file
MAX_MATCHES = 10
# How often what's found so far is sent to the picker, with how far it's got, in seconds
SEND_INTERVAL = 0.1
# How many of a file's siblings are looked for in a match's dir: a few say enough
SIBLINGS_TRIED = 10
# The smallest file whose files of its size (with other names) are candidates too: smaller sizes
# are too common to say much
RENAMED_MIN_SIZE = 64 * 1024
# Modification times this close are the same (FAT keeps them to 2 seconds), in seconds
SAME_TIME = 2
# What says a candidate is surely the file, in its preview: highlighted, so it's seen when it comes
SURELY_MOVED = picker.highlighted("→ surely this file, moved")
SURELY_RENAMED = picker.highlighted("→ surely this file, renamed")

# The hashes that Drive gives (drivecache.HASH_FIELDS), the fastest to work out first
_HASH_PREFERENCE = ('sha1', 'sha256')

# A candidate in the other replica: its relpath, size, date taken and modification time (or None),
# how many of the file's siblings (of how many tried) are in its dir too, whether its contents are
# the same (None: not compared), and whether it has another name than the file's
Match = collections.namedtuple('Match', ['relpath', 'size', 'date_taken', 'modified', 'siblings_found',
                                         'siblings_tried', 'same_contents', 'is_other_name'])


class Index(object):
    """A replica's files by name (and the big ones by size), built once (in the background, by
    find_previews(), or by sure_matches()), and then kept up to date as files are copied into the
    replica, removed from it or moved in it (add(), remove(), move()), rather than built again; or
    built again after the replica is read anew (invalidate())."""

    def __init__(self, replica):
        self.replica = replica
        # {name: {relpath: size}}, the names in each dir, {size: relpaths} of the big ones
        # (RENAMED_MIN_SIZE), and {(algorithm, hash): relpaths} of the files whose hashes are known
        # without reading them (Drive's), once built
        self._by_name = None
        self._names_by_dir = None
        self._by_size = None
        self._by_hash = None
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
        by_size = collections.defaultdict(set)
        by_hash = collections.defaultdict(set)
        for name, files in by_name.items():
            for relpath, size in files.items():
                names_by_dir[os.path.dirname(relpath)].add(name)
                if size is not None and size >= RENAMED_MIN_SIZE:
                    by_size[size].add(relpath)
                for algorithm in self.replica.known_hashes(relpath):
                    value = self.replica.content_hash(relpath, algorithm)
                    by_hash[algorithm, value].add(relpath)
                    self._hashes.setdefault(relpath, {})[algorithm] = value
        self._names_by_dir, self._by_size, self._by_hash = names_by_dir, by_size, by_hash
        # Last: is_built() says it is once all is
        self._by_name = by_name

    def invalidate(self):
        self._by_name = self._names_by_dir = self._by_size = self._by_hash = None
        self._dates_taken = {}
        self._hashes = {}

    def files_named(self, name):
        """{relpath: size} of the files with the name"""
        return self._by_name.get(name, {})

    def files_sized(self, size):
        """The relpaths of the files of the size, if it's big enough to be in (RENAMED_MIN_SIZE)"""
        return self._by_size.get(size, set())

    def hash_algorithms(self):
        """The algorithms of the hashes known of its files without reading them (Drive's), the
        fastest to work out first"""
        known = {algorithm for algorithm, _ in self._by_hash}
        return [algorithm for algorithm in _HASH_PREFERENCE if algorithm in known]

    def files_hashed(self, algorithm, value):
        """The relpaths of the files whose contents' hash by algorithm is value (of the ones known)"""
        return self._by_hash.get((algorithm, value), set())

    def names_in(self, dirpath):
        return self._names_by_dir.get(dirpath, set())

    def date_taken(self, relpath):
        if relpath not in self._dates_taken:
            self._dates_taken[relpath] = self.replica.date_taken(relpath)
        return self._dates_taken[relpath]

    def modified_time(self, relpath):
        return self.replica.modified_time(relpath)

    def content_hash(self, relpath, algorithm, should_stop=None):
        """The file's contents' hash, as the replica's content_hash() gives it (worked out once)"""
        return self.content_hashes(relpath, [algorithm], should_stop)[algorithm]

    def content_hashes(self, relpath, algorithms, should_stop=None):
        """{algorithm: hash} of the file's contents, the ones not worked out yet in one read"""
        hashes = self._hashes.setdefault(relpath, {})
        needed = [algorithm for algorithm in algorithms if algorithm not in hashes]
        if needed:
            hashes.update(self.replica.content_hashes(relpath, needed, should_stop))
        return {algorithm: hashes[algorithm] for algorithm in algorithms}

    def add(self, relpath, size):
        """A file is at relpath now (unless it isn't built yet, when there's nothing to change)"""
        if self.is_built():
            name = os.path.basename(relpath)
            self._by_name.setdefault(name, {})[relpath] = size
            self._names_by_dir[os.path.dirname(relpath)].add(name)
            if size is not None and size >= RENAMED_MIN_SIZE:
                self._by_size[size].add(relpath)
            for algorithm in self.replica.known_hashes(relpath):
                self._by_hash[algorithm, self.replica.content_hash(relpath, algorithm)].add(relpath)

    def remove(self, relpath):
        if self.is_built():
            name = os.path.basename(relpath)
            files = self._by_name.get(name, {})
            size = files.pop(relpath, None)
            if not files:
                self._by_name.pop(name, None)
            self._names_by_dir.get(os.path.dirname(relpath), set()).discard(name)
            self._by_size.get(size, set()).discard(relpath)
            for algorithm, value in self._hashes.get(relpath, {}).items():
                self._by_hash.get((algorithm, value), set()).discard(relpath)
            for relpaths in self._by_hash.values():
                relpaths.discard(relpath)
        self._dates_taken.pop(relpath, None)
        self._hashes.pop(relpath, None)

    def move(self, relpath, new_relpath):
        # The same file, with the same contents
        hashes = self._hashes.get(relpath)
        known = ({key for key, relpaths in self._by_hash.items() if relpath in relpaths}
                 if self.is_built() else set())
        if self.is_built():
            size = self.files_named(os.path.basename(relpath)).get(relpath)
            self.remove(relpath)
            self.add(new_relpath, size)
        else:
            self.remove(relpath)
        if hashes:
            self._hashes[new_relpath] = hashes
        for key in known:
            self._by_hash[key].add(new_relpath)


def _same_sized(relpath, size, index):
    """The candidates of src's file at relpath of its size (in index): of its name, and if it's big
    enough, of other names (at most MAX_RENAMED of them), each with whether it's of another name"""
    if size is None:
        return {}
    name = os.path.basename(relpath)
    found = {match_relpath: False for match_relpath, match_size in index.files_named(name).items()
             if match_size == size}
    if size >= RENAMED_MIN_SIZE:
        found.update((match_relpath, True) for match_relpath in index.files_sized(size)
                     if os.path.basename(match_relpath) != name)
    return found


class _Matcher(object):
    """Finds the candidates of src's missing files at relpaths in the other replica's index"""

    def __init__(self, relpaths, src, index, checked=None):
        """checked: {relpath: {candidate relpath: whether its contents are the same}} of the files
        whose contents were compared (check_contents())"""
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
        """The file's candidates (Match), the likeliest first"""
        dirpath, name = os.path.split(relpath)
        size = self._src.file_size(relpath)
        candidates = dict(self._index.files_named(name))
        renamed = {match_relpath for match_relpath, is_other_name
                   in _same_sized(relpath, size, self._index).items() if is_other_name}
        checked = self._checked.get(relpath, {})
        # And the ones of other names (any size) found by the file's hash
        renamed |= {match_relpath for match_relpath, is_same in checked.items()
                    if is_same and os.path.basename(match_relpath) != name}
        candidates.update((match_relpath, self._index.files_named(os.path.basename(match_relpath)).get(match_relpath))
                          for match_relpath in renamed)
        if any(checked.get(match_relpath) for match_relpath in candidates):
            # The ones with the same contents are it: the others aren't
            candidates = {match_relpath: match_size for match_relpath, match_size in candidates.items()
                          if checked.get(match_relpath)}
        else:
            # A file of another name with other contents is just another file
            candidates = {match_relpath: match_size for match_relpath, match_size in candidates.items()
                          if not (match_relpath in renamed and checked.get(match_relpath) is False)}
        if not candidates:
            return []
        date = self.date_taken(relpath)
        modified = self._src.modified_time(relpath)
        tried = [sibling for sibling in self._siblings[dirpath] if sibling != name][:SIBLINGS_TRIED]
        found = []
        for match_relpath, match_size in candidates.items():
            match_dir = os.path.dirname(match_relpath)
            key = (dirpath, match_dir)
            if key not in self._siblings_in:
                self._siblings_in[key] = set(self._siblings[dirpath]) & self._index.names_in(match_dir)
            nr_found = sum(1 for sibling in tried if sibling in self._siblings_in[key])
            found.append(Match(match_relpath, match_size, self._index.date_taken(match_relpath),
                               self._index.modified_time(match_relpath), nr_found, len(tried),
                               checked.get(match_relpath), match_relpath in renamed))
        return sorted(found, key=lambda match: _unlikeliness(match, size, date, modified))


def _is_same_time(time_a, time_b):
    return time_a is not None and time_b is not None and abs(time_a - time_b) <= SAME_TIME


def _unlikeliness(match, size, date, modified):
    """What sorts a match after the likelier ones (see the module's doc), then by path"""
    is_size_known = size is not None and match.size is not None
    return (match.same_contents is not True, match.same_contents is False, match.is_other_name,
            not (is_size_known and match.size == size),
            not (date is not None and match.date_taken == date),
            -(match.siblings_found / match.siblings_tried if match.siblings_tried else 0),
            not _is_same_time(match.modified, modified),
            not is_size_known, abs(match.size - size) if is_size_known else 0,
            match.relpath.split('/'))


def sure_match(matches, size, date):
    """Of a file's candidates (likeliest first), the one surely the same file, moved or renamed, or
    None: of the ones with the same contents, the only one, or the one with more of the file's
    siblings than any other; with none, of the same name, the only one of the same size whose
    contents weren't found to be other (not compared yet, or they can't be, e.g. a Google file's;
    so after check_all(), the contents decide where they can), and with the same date taken where
    both are known, or of several, the one with the most siblings."""
    same = [match for match in matches if match.same_contents]
    if not same:
        same = [match for match in matches
                if not match.is_other_name and size is not None and match.size == size and
                match.same_contents is None and
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


def may_be_elsewhere(relpaths, src, index, checked=None):
    """Of src's missing files at relpaths, the ones that may be in index (built if it isn't), moved
    or renamed: with a sure match by what's known now, or whose contents weren't compared yet with
    their candidates of their size, or with what index knows by hash (check_all() then says)"""
    checked = checked if checked is not None else {}
    sure = sure_matches(relpaths, src, index, checked)
    return [relpath for relpath in relpaths
            if relpath in sure or relpath in to_check([relpath], src, index, checked)]


def find_previews(relpaths, src, index, send, checked=None):
    """Find, for each of src's files at relpaths (which the other replica, index's, lacks at those
    paths), where the other replica may have it, and send() them (picker.pick_files()'s previews)
    as they're found (see _preview()). Until a file's are sent, the picker shows how far it's got:
    building the index (if it isn't), then matching. Lets picker.PickerClosed go up, once the
    picker is gone. checked: as _Matcher's."""
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
    picker.Selection), once index is built: send its preview at once (rather than when
    find_previews() gets to it), then compare its contents with those of its candidates of its size
    (_check()), and send its preview again. Each file once: checked has it then. Reading a local
    file may take a while, so it's stopped when the selection moves on, for the file it's on now.
    Lets picker.PickerClosed go up, once the picker is gone."""
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
        if relpath not in missing:
            continue
        matcher = matcher or _Matcher(relpaths, src, index, checked)
        candidates = _same_sized(relpath, src.file_size(relpath), index)
        if relpath in checked or not (candidates or index.hash_algorithms()):
            send({relpath: _preview(relpath, src, dst_name, matcher)})
            continue
        send({relpath: _preview(relpath, src, dst_name, matcher) +
              ["", "Comparing its contents with the", "%s of its size%s..." %
               (_files(len(candidates)), " and %s's by hash" % (dst_name,) if index.hash_algorithms() else "")]})
        try:
            _check(relpath, candidates, src, src_index, index, checked,
                   lambda: not selection.is_at(relpath))
        except dirtree.HashStopped:
            # Moved on: its preview as it was, and on to where the selection is now
            send({relpath: _preview(relpath, src, dst_name, matcher)})
            pending = selection.wait_next(0)
            continue
        send({relpath: _preview(relpath, src, dst_name, matcher)})


def to_check(relpaths, src, index, checked):
    """Of src's missing files at relpaths, the ones whose contents weren't compared yet with their
    candidates of their size in index (built if it isn't), which they have"""
    index.build()
    return [relpath for relpath in relpaths
            if relpath not in checked and (index.hash_algorithms() or
                                           _same_sized(relpath, src.file_size(relpath), index))]


def check_all(relpaths, src, src_index, index, checked, progress=None):
    """Compare the contents of each of src's missing files at relpaths that wasn't yet with its
    candidates of its size in index (built if it isn't), as check_contents() does, calling
    progress(number, count, relpath) before each (count: how many need it). Stopped by Ctrl-C (it's
    let go up): what was compared is kept."""
    needed = to_check(relpaths, src, index, checked)
    for number, relpath in enumerate(needed, 1):
        if progress is not None:
            progress(number, len(needed), relpath)
        _check(relpath, _same_sized(relpath, src.file_size(relpath), index), src, src_index, index,
               checked, lambda: False)


def _check(relpath, candidates, src, src_index, index, checked, should_stop):
    """Compare the contents of src's file at relpath with those of candidates (relpaths in index;
    see _same_contents()), and if index knows its files' hashes (Drive's), look its own up there
    (any name and size), and note which are the same in checked[relpath] (not those where it
    couldn't be told, e.g. a Google file's, which has no hash). Raises dirtree.HashStopped once
    should_stop() says to, noting nothing."""
    found = {}
    algorithms = index.hash_algorithms()
    if algorithms:
        # All in one read of a local file
        for algorithm, value in src_index.content_hashes(relpath, algorithms, should_stop).items():
            if value is not None:
                found.update((match_relpath, True) for match_relpath in index.files_hashed(algorithm, value))
    found.update((match_relpath, _same_contents(src, src_index, relpath, index, match_relpath, should_stop))
                 for match_relpath in candidates if match_relpath not in found)
    checked[relpath] = {match_relpath: is_same for match_relpath, is_same in found.items()
                        if is_same is not None}


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
    """The lines about src's file at relpath: its size, date taken and modification time, and its
    candidates, the likeliest first, of its name, then of other names, each with its dir, size,
    date taken, modification time, siblings found and contents, and which is surely the file, if
    one is; or that there are none"""
    matches = matcher.matches(relpath)
    size = src.file_size(relpath)
    # Read only for a file with candidates: they're to compare with
    date = matcher.date_taken(relpath) if matches else None
    modified = src.modified_time(relpath) if matches else None
    about = [format_size(size)] if size is not None else []
    if date is not None:
        about.append("taken " + date)
    lines = ["This one: " + ", ".join(about)] if about else []
    if modified is not None:
        lines.append("  modified " + _format_time(modified))
    named = [match for match in matches if not match.is_other_name]
    renamed = [match for match in matches if match.is_other_name]
    sure = sure_match(matches, size, date)
    if named:
        lines.append("In %s, likeliest first:" % (dst_name,))
        lines += _matches_lines(named, size, date, modified, sure, SURELY_MOVED)
    else:
        lines += ["In %s:" % (dst_name,), "  no file of this name"]
    if renamed:
        lines.append("Of its size, another name:")
        lines += _matches_lines(renamed, size, date, modified, sure, SURELY_RENAMED)
    return lines


def _matches_lines(matches, size, date, modified, sure, surely):
    lines = []
    for match in matches[:MAX_MATCHES]:
        dirpath, name = os.path.split(match.relpath)
        lines += ["  %s/" % (dirpath or '.',), "    %s%s" % (name, _size_note(match.size, size))]
        if match.date_taken is not None:
            lines.append("    taken %s%s" % (match.date_taken,
                                             ", the same" if match.date_taken == date else ""))
        if match.modified is not None:
            lines.append("    modified %s%s" % (_format_time(match.modified),
                                                _time_note(match.modified, modified)))
        if match.siblings_tried:
            lines.append("    with %d of %d of its dir's files" % (match.siblings_found,
                                                                   match.siblings_tried))
        if match.same_contents is not None:
            lines.append("    the same contents" if match.same_contents else "    other contents")
        if match is sure:
            lines.append(surely)
    if len(matches) > MAX_MATCHES:
        lines.append("(and %d more)" % (len(matches) - MAX_MATCHES,))
    return lines


def _format_time(timestamp):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))


def _time_note(match_modified, modified):
    """Whether a match's modification time is the same as the file's, or newer, or older"""
    if modified is None:
        return ""
    if _is_same_time(match_modified, modified):
        return ", the same"
    return ", newer" if match_modified > modified else ", older"


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
