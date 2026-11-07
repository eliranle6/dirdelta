"""A sync's two ways (src's files that dst lacks), and the files that differ, found in the background"""
import concurrent.futures
import threading

from dirdelta.matching import differing
from dirdelta.sync import replica_ops
from dirdelta.util import text


files_text = text.files

# The sync menu's option of the files both replicas have that differ
DIFFER = "Files that differ"


def differ_word(count):
    return "differs" if count == 1 else "differ"


def find_all(ways, compared=None):
    """Start finding (again) what each way lacks, and the files both have that differ (see
    find_differing())"""
    for way in ways:
        way.find_missing()
    find_differing(ways, compared)


def find_differing(ways, compared=None):
    """Start finding (again) the files both ways' replicas have that differ: once, for both ways (the
    second's, flipped); compared: as differing.find()'s, the first way's"""
    way_a, way_b = ways
    way_a.differs, way_b.differs = concurrent.futures.Future(), concurrent.futures.Future()

    def find(futures=(way_a.differs, way_b.differs)):
        try:
            changes = differing.find(way_a.src, way_a.dst, compared)
        except Exception as error:
            for future in futures:
                future.set_exception(error)
        else:
            futures[0].set_result(changes)
            futures[1].set_result(differing.flipped(changes))
    threading.Thread(target=find, daemon=True).start()


class Way(object):
    """One way of the sync: src's files that dst lacks (a future of Missing), found in the
    background, the replicas' indexes (elsewhere.Index, by replica), and which of src's files
    have the same contents as their matches"""
    def __init__(self, src, dst, indexes):
        self.src = src
        self.dst = dst
        self.indexes = indexes
        # Which of src's files' matches in dst have the same contents (see
        # elsewhere.check_contents()), kept so each is compared once
        self.checked = {}
        # The files of the same size compared on request (see comparing.py), the sync menu's (a
        # same-sized pair's sizes are the same either way)
        self.compared = {}
        self.missing = None
        # A future of the files both have that differ, src's way (differing.find(), see find_all())
        self.differs = None

    def find_missing(self):
        """Start finding them (again), on a thread of its own, which doesn't keep dirdelta from
        exiting"""
        self.missing = concurrent.futures.Future()
        threading.Thread(target=self._find_missing, args=(self.missing,), daemon=True).start()

    def _find_missing(self, missing):
        try:
            missing.set_result(replica_ops.find_missing(self.src, self.dst))
        except Exception as error:
            # Raised by result(), when the files are needed
            missing.set_exception(error)
