"""The combined tree's moved pairs: a file only in A and one only in B with the same contents, as far
as is known without reading them (the hashes known of both, or what was compared before), so a pair
is never a guess"""
import collections
import difflib

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


def path_diff(old, new):
    """[(text, style)] of how the path new differs from old, word by word (a word: a dir's name, with its
    '/', or the file's name), as git's word diff shows it: what's only in old [-red-], what's only in new
    {+green+}, the rest as it is; e.g. old/moved.txt -> docs/moved.txt: [-old/-]{+docs/+}moved.txt"""
    old_words, new_words = _words(old), _words(new)
    parts = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_words, new_words, autojunk=False).get_opcodes():
        if tag == 'equal':
            parts.append((''.join(old_words[i1:i2]), None))
            continue
        if i2 > i1:
            parts.append(('[-%s-]' % (''.join(old_words[i1:i2]),), 'red'))
        if j2 > j1:
            parts.append(('{+%s+}' % (''.join(new_words[j1:j2]),), 'green'))
    return parts


def _words(path):
    """A path's words: each dir's name with its '/', then the file's name"""
    names = path.split('/')
    return [name + '/' for name in names[:-1]] + names[-1:]
