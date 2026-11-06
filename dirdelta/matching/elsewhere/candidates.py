"""The other replica's files that may be a file: of its name, of its size, of its contents"""
import collections
import os

from dirdelta.matching.elsewhere.constants import Match, RENAMED_MIN_SIZE, SAME_TIME, SIBLINGS_TRIED


def matches_of_size(relpath, size, index):
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


def known_same(relpath, src_index, index, candidates=()):
    """{relpath in index: whether its contents are the same} as src_index's file at relpath, by the
    hashes known of both without reading them (see Index.known()): the ones of index with the
    file's hash, whatever their names and sizes, and of candidates (relpaths in index), the ones
    with another hash by the same algorithm"""
    own = src_index.known(relpath)
    found = {}
    for algorithm, value in own.items():
        found.update((match_relpath, True) for match_relpath in index.files_hashed(algorithm, value))
    for match_relpath in candidates:
        if match_relpath in found:
            continue
        other = index.known(match_relpath)
        if any(algorithm in other and other[algorithm] != value for algorithm, value in own.items()):
            found[match_relpath] = False
    return found


class _Matcher(object):
    """Finds the candidates of src's missing files at relpaths in the other replica's index"""

    def __init__(self, relpaths, src, index, checked=None, src_index=None):
        """checked: {relpath: {candidate relpath: whether its contents are the same}} of the files
        whose contents were compared (check_contents()). src_index: src's Index, whose hashes known
        without reading (its hashing job's, or Drive's) tell the contents too (known_same())."""
        self._src = src
        self._index = index
        self.src_index = src_index
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

    def compared(self, relpath, same_sized=None):
        """{candidate relpath: whether its contents are the same} as the file's, as compared, or as
        the hashes known of both say"""
        checked = dict(self._checked.get(relpath, {}))
        if self.src_index is not None:
            if same_sized is None:
                same_sized = matches_of_size(relpath, self._src.file_size(relpath), self._index)
            for match_relpath, is_same in known_same(relpath, self.src_index, self._index, same_sized).items():
                checked.setdefault(match_relpath, is_same)
        return checked

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
        same_sized = matches_of_size(relpath, size, self._index)
        renamed = {match_relpath for match_relpath, is_other_name in same_sized.items() if is_other_name}
        checked = self.compared(relpath, same_sized)
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
