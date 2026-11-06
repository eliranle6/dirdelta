"""The candidates that are surely the file"""
from dirdelta.matching.elsewhere.candidates import Matcher, matches_of_size


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


def sure_matches(relpaths, src, index, checked=None, src_index=None):
    """{relpath: the relpath of its sure match (see sure_match())} of src's missing files at relpaths
    that have one in index (built if it isn't); checked, src_index: as _Matcher's"""
    index.build()
    matcher = Matcher(relpaths, src, index, checked, src_index)
    found = {}
    for relpath in relpaths:
        matches = matcher.matches(relpath)
        match = (sure_match(matches, src.file_size(relpath), matcher.date_taken(relpath))
                 if matches else None)
        if match is not None:
            found[relpath] = match.relpath
    return found


def may_be_elsewhere(relpaths, src, index, checked=None, src_index=None):
    """Of src's missing files at relpaths, the ones that may be in index (built if it isn't), moved
    or renamed: with a sure match by what's known now, or whose contents weren't compared yet with
    their candidates of their size, or with what index knows by hash (check_all() then says)"""
    checked = checked if checked is not None else {}
    sure = sure_matches(relpaths, src, index, checked, src_index)
    return [relpath for relpath in relpaths
            if relpath in sure or relpath in to_check([relpath], src, index, checked)]


def to_check(relpaths, src, index, checked):
    """Of src's missing files at relpaths, the ones whose contents weren't compared yet with their
    candidates of their size in index (built if it isn't), which they have"""
    index.build()
    return [relpath for relpath in relpaths
            if relpath not in checked and (index.hash_algorithms() or
                                           matches_of_size(relpath, src.file_size(relpath), index))]
