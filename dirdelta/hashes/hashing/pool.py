"""The threads that hash the jobs' files, and how many there are"""
import glob
import os
import threading

from dirdelta.hashes.hashing.reading import lower_priority


class _Pool(object):
    """The worker threads, shared by all the jobs, taking their files in turn"""

    def __init__(self, nr_workers):
        self.nr_workers = nr_workers
        self._jobs = []
        self._condition = threading.Condition()
        self._threads = []
        # Which job the next file is taken from first (in turn)
        self._turn = 0

    def add(self, job):
        with self._condition:
            if job not in self._jobs:
                self._jobs.append(job)
            while len(self._threads) < self.nr_workers:
                thread = threading.Thread(target=self._work, daemon=True)
                self._threads.append(thread)
                thread.start()
            self._condition.notify_all()

    def wake(self):
        """Look for files to hash again (e.g. a job was scanned anew, or a worker finished)"""
        with self._condition:
            self._condition.notify_all()

    def _take(self):
        """(job, relpath) of the next file to hash, or None"""
        with self._condition:
            for i in range(len(self._jobs)):
                job = self._jobs[(self._turn + i) % len(self._jobs)]
                relpath = job._next()
                if relpath is not None:
                    self._turn = (self._turn + i + 1) % len(self._jobs)
                    return job, relpath
            return None

    def _work(self):
        lower_priority()
        while True:
            task = self._take()
            if task is None:
                with self._condition:
                    # Woken when there may be more (or now and then, e.g. a job of a spinning disk
                    # whose one worker finished)
                    self._condition.wait(1)
                continue
            job, relpath = task
            try:
                job._hash(relpath)
            finally:
                self.wake()


_the_pool = None
_pool_lock = threading.Lock()


def pool():
    global _the_pool
    with _pool_lock:
        if _the_pool is None:
            _the_pool = _Pool(nr_workers())
        return _the_pool


def nr_workers():
    """How many threads hash: one fewer than the machine's physical cores (at least one)"""
    return max(1, physical_cores() - 1)


def physical_cores():
    """How many physical cores the machine has (not hyper-threads), from /sys; or half its logical
    ones, if it can't tell"""
    cores = set()
    for path in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/topology/core_id'):
        try:
            with open(path) as core_file, open(os.path.join(os.path.dirname(path), 'physical_package_id')) as package_file:
                cores.add((package_file.read().strip(), core_file.read().strip()))
        except OSError:
            continue
    return len(cores) or max(1, (os.cpu_count() or 2) // 2)


def is_rotational(path):
    """Whether the local path is on a spinning disk (False if it can't tell)"""
    try:
        device = os.stat(path).st_dev
        block = os.path.realpath('/sys/dev/block/%d:%d' % (os.major(device), os.minor(device)))
    except OSError:
        return False
    # A partition's queue is its disk's, the dir above it
    for dirpath in (block, os.path.dirname(block)):
        try:
            with open(os.path.join(dirpath, 'queue', 'rotational')) as rotational:
                return rotational.read().strip() == '1'
        except OSError:
            continue
    return False
