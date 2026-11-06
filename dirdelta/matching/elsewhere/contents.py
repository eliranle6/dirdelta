"""Comparing the files' contents with their candidates'"""
import hashlib

from dirdelta.hashes import hashcache
from dirdelta.matching.elsewhere.candidates import _Matcher, matches_of_size
from dirdelta.matching.elsewhere.constants import _HASH_PREFERENCE
from dirdelta.matching.elsewhere.preview_lines import _files, _preview
from dirdelta.matching.elsewhere.sure import to_check
from dirdelta.trees import dirtree


INDEX_WAIT_INTERVAL = 0.2


def check_contents(relpaths, src, src_index, index, checked, selection, send, sends_previews=True):
    """For each of src's missing files at relpaths as it's selected in the picker (selection, a
    picker.Selection), once index is built: send its preview at once (rather than when
    find_previews() gets to it), then compare its contents with those of its candidates of its size
    (_check()), and send its preview again. Each file once: checked has it then. Reading a local
    file may take a while, so it's stopped when the selection moves on, for the file it's on now.
    Without sends_previews, it sends nothing (its caller sends its own previews, from checked).
    Lets picker.PickerClosed go up, once the picker is gone."""
    if not sends_previews:
        send = lambda found=None, default=None: None
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
        matcher = matcher or _Matcher(relpaths, src, index, checked, src_index)
        candidates = matches_of_size(relpath, src.file_size(relpath), index)
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


def check_all(relpaths, src, src_index, index, checked, progress=None):
    """Compare the contents of each of src's missing files at relpaths that wasn't yet with its
    candidates of its size in index (built if it isn't), as check_contents() does, calling
    progress(number, count, relpath) before each (count: how many need it). Stopped by Ctrl-C (it's
    let go up): what was compared is kept."""
    needed = to_check(relpaths, src, index, checked)
    for number, relpath in enumerate(needed, 1):
        if progress is not None:
            progress(number, len(needed), relpath)
        _check(relpath, matches_of_size(relpath, src.file_size(relpath), index), src, src_index, index,
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
        # Their hashes, if both are kept from before (the hash cache); else read side by side
        hashes = [hashcache.get(path, 'sha1'), hashcache.get(match_path, 'sha1')]
        if None not in hashes:
            return hashes[0] == hashes[1]
        return _same_bytes(path, match_path, should_stop)
    known = set(src.known_hashes(relpath)) | set(index.replica.known_hashes(match_relpath))
    for algorithm in [algorithm for algorithm in _HASH_PREFERENCE if algorithm in known]:
        own = src_index.content_hash(relpath, algorithm, should_stop)
        other = index.content_hash(match_relpath, algorithm, should_stop)
        if own is not None and other is not None:
            return own == other
    return None


def _same_bytes(path, other_path, should_stop):
    """Whether the files at the paths have the same contents, or None if they can't be read. Ones
    found the same (read whole) get their hash kept in the hash cache, for the next time."""
    digest = hashlib.sha1()
    try:
        with open(path, 'rb') as f, open(other_path, 'rb') as other:
            while True:
                if should_stop():
                    raise dirtree.HashStopped()
                chunk = f.read(COMPARE_READ_SIZE)
                if chunk != other.read(COMPARE_READ_SIZE):
                    return False
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    for same_path in (path, other_path):
        hashcache.put(same_path, {'sha1': digest.hexdigest()})
    return True
