"""Comparing, on request, the files two replicas both have at the same paths, of the same size,
whose hashes aren't both known (differing.find()'s uncompared): two local files read side by side,
with a Drive file by its hash (elsewhere.same_contents())"""
import time

from dirdelta.hashes import hashing
from dirdelta.matching import elsewhere
from dirdelta.sync import replica_ops
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun

# The sync menu's option that compares them
COMPARE = "Compare the files of the same size"


def shown_as(differs):
    """The sync menu's option of comparing the files of the same size not compared yet, as it's shown
    now, by differs (the first way's future of differing.find()): their count, or greyed out (a
    picker.Disabled) while they're found, or if there are none"""
    label = "%s at the same paths in both" % (COMPARE,)
    if differs is None or not differs.done():
        return picker.Disabled("%s (loading...)" % (label,))
    if differs.exception() is not None or not differs.result().uncompared:
        return picker.Disabled("%s: none not compared" % (label,))
    return "%s, not compared yet (%s)" % (label, replica_ops.files_text(len(differs.result().uncompared)))


def compare(relpaths, src, dst, src_index, dst_index, compared):
    """Compare src's files at relpaths with dst's at the same paths, on a progress screen (stoppable:
    what was compared is kept), noting in compared {relpath: (src's size, dst's size, whether
    they're the same)} (see differing.find()); the ones that couldn't be told (unreadable, or a
    Drive file with no hash) aren't noted. Returns how many differ of those compared."""
    nr_differ = nr_done = 0
    with messages.progress_screen("Comparing %s of the same size in %s and %s" % (
            replica_ops.files_text(len(relpaths)), src.displayname(), dst.displayname()), dryrun.label()):
        try:
            for number, relpath in enumerate(relpaths, 1):
                messages.print_progress("Comparing %d of %d: %s" % (number, len(relpaths), relpath))
                is_same = elsewhere.same_contents(src, src_index, relpath, dst_index, relpath, lambda: False)
                if is_same is None:
                    continue
                compared[relpath] = (src.file_size(relpath), dst.file_size(relpath), is_same)
                nr_done += 1
                nr_differ += not is_same
        except KeyboardInterrupt:
            messages.note_stopped()
        messages.print_line("")
        messages.print_line("Compared %s: %d %s." % (replica_ops.files_text(nr_done), nr_differ,
                                                     "differs" if nr_differ == 1 else "differ"))
    return nr_differ


# How often, at most, the files that differ are found again while the local replicas are being hashed
# (as each file hashed may settle one not compared), in seconds; at once when a replica's hashing is done
REFIND_INTERVAL = 30


class AsHashed(object):
    """When to find the files that differ again (sync.ways.find_differing()) as the jobs (the local
    replicas' hashing jobs) hash their files: some not compared (differing.find()'s uncompared) may
    be told then, without reading them"""
    def __init__(self, jobs):
        self._jobs = jobs
        self._found_at = None
        self._nr_hashed = None

    def found(self):
        """Note that the files that differ are being found now"""
        self._found_at = time.monotonic()
        self._nr_hashed = self._hashed()

    def is_due(self, differs):
        """Whether to find them again: differs (the first way's future of differing.find()) is done,
        with files not compared, and more files were hashed since, and either a job is done or
        REFIND_INTERVAL went by"""
        if not differs.done() or differs.exception() is not None or not differs.result().uncompared:
            return False
        if self._hashed() == self._nr_hashed:
            return False
        progresses = [job.progress() for job in self._jobs]
        return (any(progress.state == hashing.DONE for progress in progresses) or
                time.monotonic() - self._found_at >= REFIND_INTERVAL)

    def _hashed(self):
        return sum(job.progress().nr_done for job in self._jobs)
