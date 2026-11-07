"""The combined tree's moved pairs: a file only in A and one only in B with the same contents, as far
as is known without reading them (the hashes known of both, or what was compared before), so a pair
is never a guess"""
import collections

from dirdelta.matching.elsewhere import candidates


def find(only_a, only_b, replica_a, index_a, index_b, checked=None):
    """{relpath only in A: the relpath only in B with the same contents} of the files at only_a and
    only_b (relpaths), each pair one to one (a file with the same contents as several of the other's,
    as duplicates, isn't paired); index_a, index_b: the replicas' elsewhere.Index (built if they
    aren't), checked: as elsewhere.Matcher's (A's way's)"""
    if not only_a or not only_b:
        return {}
    only_b = set(only_b)
    index_a.build()
    index_b.build()
    matcher = candidates.Matcher(only_a, replica_a, index_b, checked, index_a)
    found = {}
    for relpath in only_a:
        same = [match for match, is_same in matcher.compared(relpath).items() if is_same and match in only_b]
        if len(same) == 1:
            found[relpath] = same[0]
    claimed = collections.Counter(found.values())
    return {relpath: match for relpath, match in found.items() if claimed[match] == 1}
