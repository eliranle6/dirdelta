"""The previews of the missing files, sent to the picker as they're found"""
import collections
import time

from dirdelta.known import replicanames
from dirdelta.matching.elsewhere.candidates import Matcher
from dirdelta.matching.elsewhere.constants import SEND_INTERVAL
from dirdelta.matching.elsewhere.preview_lines import preview_of
from dirdelta.ui import picker


# How often find_previews() looks for files hashed meanwhile, whose previews change, in seconds
HASHED_INTERVAL = 1


def find_previews(relpaths, src, index, send, checked=None, src_index=None):
    """Find, for each of src's files at relpaths (which the other replica, index's, lacks at those
    paths), where the other replica may have it, and send() them (picker.pick_files()'s previews)
    as they're found (see preview_of()). Until a file's are sent, the picker shows how far it's got:
    building the index (if it isn't), then matching. Then, while either replica is being hashed
    (hashing.py), send again the previews of the files that it changes: the ones hashed, and the
    ones of the hash of a file of index's hashed. Lets picker.PickerClosed go up, once the picker is
    gone. checked, src_index: as _Matcher's."""
    dst_name = index.replica.displayname()
    # (A status, in grey, by the replica's one name: e.g. "Finding where Grey HD has them: 4,223 of its files listed")
    title = "Finding where %s has them" % (replicanames.name(dst_name),)

    def status(how_far):
        return [picker.styled([("%s: %s..." % (title, how_far), 'grey')])]
    is_due = _Throttle(SEND_INTERVAL)
    send(default=status("listing its files"))
    try:
        index.build(lambda count: is_due() and send(default=status("{:,} of its files listed".format(count))))
        matcher = Matcher(relpaths, src, index, checked, src_index)
        if src_index is not None:
            # What's hashed from now on changes the previews (what was is in them)
            src_index.take_new()
        index.take_new()
        found = {}
        for i, relpath in enumerate(relpaths):
            found[relpath] = preview_of(relpath, src, dst_name, matcher)
            if is_due():
                send(found, default=status("{:,} of {:,} files matched".format(i + 1, len(relpaths))))
                found = {}
    except (OSError, ValueError) as error:
        send(default=["Couldn't find where %s has them:" % (replicanames.name(dst_name),), str(error)])
        return
    # Dirs show nothing
    send(found, default=[])
    if src_index is None or (src_index.job() is None and index.job() is None):
        return
    missing = set(relpaths)
    # src's missing files by their hashes known (to find the ones of index's files hashed)
    by_hash = collections.defaultdict(set)
    for relpath in relpaths:
        for key in src_index.known(relpath).items():
            by_hash[key].add(relpath)
    # (The picker's pause, which ends as soon as it's gone, rather than its closing waiting for the sleep)
    pause = getattr(send, 'pause', time.sleep)
    while True:
        pause(HASHED_INTERVAL)
        changed = src_index.take_new() & missing
        for relpath in changed:
            for key in src_index.known(relpath).items():
                by_hash[key].add(relpath)
        for match_relpath in index.take_new():
            for key in index.known(match_relpath).items():
                changed |= by_hash.get(key, set())
        # Sent even with nothing to send: it raises PickerClosed once the picker is gone
        send({relpath: preview_of(relpath, src, dst_name, matcher) for relpath in changed})


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
