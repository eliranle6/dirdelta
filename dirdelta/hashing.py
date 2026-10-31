"""Hashing local replicas' files in the background, all of them, so a file can be looked up by its
contents (elsewhere.py) as Drive's are, whatever its name and size: a moved or renamed file, or an
inbox's copy of a sorted tree's file, is found without reading it then.

Each local replica has a Job: scan() lists its files (one find, with their sizes and modification
times) and tells, from the hash cache (hashcache.py), which are hashed already; start() hashes the
rest, in the background, until pause(). The hashes go to the hash cache, where they're kept for next
time, and to the job's subscribers (elsewhere.Index), as each file is hashed.

The hash is SHA-1, the cheapest of the hashes Drive gives (drivecache.HASH_FIELDS), so a local file
is compared with a Drive one by it too; MD5 is slower in Python's hashlib (with SHA-NI), and Drive's
file list cache doesn't keep it. The files are read by a pool of threads shared by all the jobs: one
fewer than the machine's physical cores (hashlib and reading let go of the GIL), at the lowest CPU
and I/O priority, and without filling the page cache with them; a job of a spinning disk's replica
uses one of them at a time, since reading several files at once makes a disk seek between them."""
import collections
import ctypes
import glob
import hashlib
import os
import platform
import subprocess
import threading
import time

from dirdelta import hashcache

ALGORITHM = 'sha1'
# How much of a file is read at a time (pausing between reads)
READ_SIZE = 1 << 20
# How many seconds of hashing the speed (and so how long is left) is worked out of
RATE_WINDOW = 10

# A job's states: not scanned yet, scanning (listing its files), scanned (not hashing: not started,
# or paused), hashing, and done (all its files hashed, as of its last scan)
NOT_SCANNED = 'not scanned'
SCANNING = 'scanning'
SCANNED = 'scanned'
HASHING = 'hashing'
DONE = 'done'

# How far a job has got: how many files it has, how many are hashed (or couldn't be), and their
# sizes; the files being hashed now; how fast it hashes (bytes a second, None if not known); how
# many couldn't be hashed (unreadable, or changing while read), and whether it's paused (started,
# then paused) or started at all
Progress = collections.namedtuple('Progress', ['state', 'nr_files', 'nr_done', 'size', 'size_done',
                                               'current', 'rate', 'nr_failed', 'is_paused', 'is_started'])


class Job(object):
    """Hashing a local replica's files (see the module's doc)"""

    def __init__(self, root, max_depth=None):
        self.root = os.path.realpath(root)
        self.max_depth = max_depth
        self.max_workers = 1 if is_rotational(self.root) else None
        self._lock = threading.Lock()
        # Whether it was scanned, is being scanned, is hashing (started), and ever was
        self._is_scanned = False
        self._is_scanning = False
        self._is_started = False
        self._was_started = False
        # {relpath: (size, mtime_ns)} of its files, as of the scan, and {relpath: hash} of the ones
        # hashed; the ones left (find's order: a dir's files together), and the ones to hash first
        self._files = {}
        self._hashes = {}
        self._left = collections.deque()
        self._first = collections.deque()
        # The ones that couldn't be hashed (unreadable, or changing while read), and the ones being
        # hashed now
        self._failed = set()
        self._current = set()
        self._size_done = 0
        # (time, bytes hashed) as the files are, for the rate
        self._samples = collections.deque()
        self._subscribers = []
        self._nr_workers = 0
        self.error = None

    def name(self):
        """The replica's name for the screens: its dir's name"""
        return os.path.basename(self.root) or self.root

    # Scanning

    def scan(self):
        """List its files, and tell which are hashed already (from the hash cache); the rest are
        left to hash. Again after its files changed (e.g. copied into it): the hashed ones are kept."""
        with self._lock:
            self._is_scanning = True
        try:
            listed = _list_files(self.root, self.max_depth)
        except OSError as error:
            with self._lock:
                self.error = str(error)
                self._is_scanning = False
            return
        kept = hashcache.known_under(self.root)
        hashes, left, size_done = {}, [], 0
        for relpath, stamp in listed.items():
            known = kept.get(relpath)
            if known is not None and known[:2] == stamp and ALGORITHM in known[2]:
                hashes[relpath] = known[2][ALGORITHM]
                size_done += stamp[0]
            else:
                left.append(relpath)
        with self._lock:
            new = {relpath: value for relpath, value in hashes.items() if self._hashes.get(relpath) != value}
            self._files, self._hashes = listed, hashes
            # The ones that couldn't be hashed are tried again
            self._failed = set()
            self._left = collections.deque(left)
            self._first = collections.deque(relpath for relpath in self._first if relpath in listed)
            self._size_done = size_done
            self.error = None
            self._is_scanned, self._is_scanning = True, False
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            for relpath, value in new.items():
                subscriber(relpath, {ALGORITHM: value})
        if self._is_started:
            _pool().wake()

    def scan_in_background(self):
        threading.Thread(target=self.scan, daemon=True).start()

    # Hashing

    def start(self):
        """Hash the files left, in the background (resuming, if paused)"""
        with self._lock:
            self._is_started = self._was_started = True
        _pool().add(self)

    def pause(self):
        """Stop hashing (the files being hashed stop where they are), until start()"""
        with self._lock:
            self._is_started = False

    def is_started(self):
        return self._is_started

    def first(self, relpaths):
        """Hash the files at relpaths before the others (e.g. the ones a picker shows)"""
        with self._lock:
            self._first.extend(relpath for relpath in relpaths
                               if relpath in self._files and relpath not in self._hashes)

    def _next(self):
        """The next file to hash, taken off what's left, or None"""
        with self._lock:
            if not self._is_started:
                return None
            if self.max_workers is not None and self._nr_workers >= self.max_workers:
                return None
            for queue in (self._first, self._left):
                while queue:
                    relpath = queue.popleft()
                    if relpath in self._files and relpath not in self._hashes and relpath not in self._current:
                        self._current.add(relpath)
                        self._nr_workers += 1
                        return relpath
            return None

    def _take(self, relpath):
        """Take the file at relpath to hash it now (as _next() does), if it isn't hashed or being
        hashed. Returns whether it was taken."""
        with self._lock:
            if relpath not in self._files or relpath in self._hashes or relpath in self._current:
                return False
            self._current.add(relpath)
            self._nr_workers += 1
            return True

    def _hash(self, relpath):
        """Hash the file (a worker's), unless it's paused meanwhile (then it's left for later)"""
        path = os.path.join(self.root, relpath)
        value, stamp = None, None
        try:
            value = hashcache.get(path, ALGORITHM)
            if value is None:
                value, stamp = _hash_file(path, lambda: not self._is_started)
        except _Paused:
            with self._lock:
                self._current.discard(relpath)
                self._nr_workers -= 1
                self._first.appendleft(relpath)
            return
        if value is not None and stamp is not None:
            hashcache.put(path, {ALGORITHM: value}, stamp)
        with self._lock:
            self._current.discard(relpath)
            self._nr_workers -= 1
            size = self._files.get(relpath, (0, 0))[0]
            if value is None:
                self._failed.add(relpath)
            else:
                self._hashes[relpath] = value
            self._size_done += size
            now = time.monotonic()
            self._samples.append((now, size))
            while self._samples and self._samples[0][0] < now - RATE_WINDOW:
                self._samples.popleft()
            subscribers = list(self._subscribers) if value is not None else []
        for subscriber in subscribers:
            subscriber(relpath, {ALGORITHM: value})

    def _state(self):
        """Its state (see NOT_SCANNED), with the lock held"""
        if not self._is_scanned:
            return SCANNING if self._is_scanning else NOT_SCANNED
        if not self._current and len(self._hashes) + len(self._failed) >= len(self._files):
            return DONE
        return HASHING if self._is_started else SCANNED

    # What it knows

    def progress(self):
        with self._lock:
            rate = None
            if len(self._samples) > 1:
                elapsed = self._samples[-1][0] - self._samples[0][0]
                if elapsed > 0:
                    rate = sum(size for _, size in list(self._samples)[1:]) / elapsed
            state = self._state()
            return Progress(state, len(self._files), len(self._hashes) + len(self._failed),
                            sum(size for size, _ in self._files.values()), self._size_done,
                            sorted(self._current), rate, len(self._failed),
                            self._was_started and not self._is_started and state == SCANNED,
                            self._is_started)

    def hash_of(self, relpath):
        """The file's hash, if it's hashed (as of the scan), else None"""
        return self._hashes.get(relpath)

    def size_of(self, relpath):
        """The file's size (as of the scan), or None if it's not one of its files"""
        stamp = self._files.get(relpath)
        return stamp[0] if stamp is not None else None

    def is_being_hashed(self, relpath):
        return relpath in self._current

    def files(self):
        """The relpaths of its files (as of the scan), each dir's together, sorted"""
        with self._lock:
            return sorted(self._files, key=lambda relpath: relpath.split('/'))

    def failed(self):
        with self._lock:
            return set(self._failed)

    def hashes(self):
        """{relpath: {algorithm: hash}} of the files hashed"""
        with self._lock:
            return {relpath: {ALGORITHM: value} for relpath, value in self._hashes.items()}

    def unsubscribe(self, subscriber):
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def subscribe(self, subscriber):
        """Call subscriber(relpath, {algorithm: hash}) as each file is hashed (from the workers'
        threads, or a scan's), from now on. Returns {relpath: {algorithm: hash}} of the ones hashed
        before."""
        with self._lock:
            self._subscribers.append(subscriber)
            return {relpath: {ALGORITHM: value} for relpath, value in self._hashes.items()}


# The jobs, by their replicas' roots
_jobs = {}
_jobs_lock = threading.Lock()


def job(root, max_depth=None):
    """The job of the local replica at root, made if there's none yet (not scanned)"""
    root = os.path.realpath(root)
    with _jobs_lock:
        if root not in _jobs:
            _jobs[root] = Job(root, max_depth)
        return _jobs[root]


def job_for(root):
    """The job of the local replica at root, if there's one, else None"""
    return _jobs.get(os.path.realpath(root))


def jobs():
    """All the jobs, in the order they were made"""
    with _jobs_lock:
        return list(_jobs.values())


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
        _lower_priority()
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


def _pool():
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


class _Paused(Exception):
    pass


def _hash_file(path, is_paused):
    """(The file's hash, its [size, mtime_ns] when it was read), or (None, None) if it can't be read
    or changed while it was. Raises _Paused once is_paused() says so."""
    digest = hashlib.new(ALGORITHM)
    try:
        with open(path, 'rb') as f:
            before = os.fstat(f.fileno())
            for chunk in iter(lambda: f.read(READ_SIZE), b''):
                if is_paused():
                    raise _Paused()
                digest.update(chunk)
            _drop_from_page_cache(f.fileno())
        after = os.stat(path)
    except OSError:
        return None, None
    stamp = [before.st_size, before.st_mtime_ns]
    if [after.st_size, after.st_mtime_ns] != stamp:
        return None, None
    return digest.hexdigest(), stamp


def _drop_from_page_cache(fd):
    """Read once, the file needn't push what the user works with out of memory"""
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    except (AttributeError, OSError):
        pass


# ioprio_set's syscall numbers, by machine, and its idle class (only when the disk is otherwise idle)
_IOPRIO_SET = {'x86_64': 251, 'aarch64': 30}
_IOPRIO_WHO_PROCESS = 1
_IOPRIO_CLASS_IDLE = 3
_IOPRIO_CLASS_SHIFT = 13


def _lower_priority():
    """The calling thread's CPU priority the lowest (nice 19), and its I/O priority idle: hashing
    gives way to anything else (on Linux; elsewhere it's as it is)"""
    try:
        thread_id = threading.get_native_id()
        os.setpriority(os.PRIO_PROCESS, thread_id, 19)
    except (AttributeError, OSError):
        return
    syscall = _IOPRIO_SET.get(platform.machine())
    if syscall is None:
        return
    try:
        ctypes.CDLL(None, use_errno=True).syscall(syscall, _IOPRIO_WHO_PROCESS, thread_id,
                                                   _IOPRIO_CLASS_IDLE << _IOPRIO_CLASS_SHIFT)
    except (OSError, AttributeError):
        pass


def _list_files(root, max_depth=None):
    """{relpath: (size, mtime_ns)} of the files under root (down to max_depth levels), by one find.
    Raises OSError if find can't be run."""
    command = ['find', root, '-mindepth', '1']
    if max_depth is not None:
        command += ['-maxdepth', str(max_depth)]
    command += ['-type', 'f', '-printf', '%s %T@ %P\\0']
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    found = {}
    for item in result.stdout.split(b'\0'):
        if not item:
            continue
        size, mtime, relpath = item.split(b' ', 2)
        found[os.fsdecode(relpath)] = (int(size), _nanoseconds(mtime.decode('ascii')))
    return found


def _nanoseconds(timestamp):
    """find's %T@ (seconds, e.g. '1698765432.1234567890') in nanoseconds, as os.stat()'s st_mtime_ns"""
    seconds, _, fraction = timestamp.partition('.')
    if seconds.startswith('-'):
        return int(round(float(timestamp) * 10 ** 9))
    return int(seconds) * 10 ** 9 + int((fraction + '000000000')[:9])


# What a file is shown as in a picker, before its name: hashed, being hashed, or not yet
HASHED_MARK = '●'
HASHING_MARK = '◐'
NOT_HASHED_MARK = '○'


def mark(job, relpath):
    """The mark of the job's file at relpath (see HASHED_MARK)"""
    if job.hash_of(relpath) is not None:
        return HASHED_MARK
    return HASHING_MARK if job.is_being_hashed(relpath) else NOT_HASHED_MARK


def percent(progress):
    """How much of the job is done, in % of its files' bytes (0-100, 100 only when it's all done);
    of its files, when they're all empty"""
    if progress.state == DONE:
        return 100
    if progress.size:
        done = progress.size_done * 100 // progress.size
    elif progress.nr_files:
        done = progress.nr_done * 100 // progress.nr_files
    else:
        done = 0
    return min(done, 99)


def color(progress):
    """The color of a job's status by how far it got: red, orange, yellow, then green once done"""
    if progress.state == DONE:
        return 'green'
    done = percent(progress)
    return 'red' if done < 34 else 'orange' if done < 67 else 'yellow'


def status_text(job, progress=None):
    """A job's status, short, for a picker's bottom line: e.g. 'photos: 63% hashed (paused)'"""
    progress = progress or job.progress()
    if progress.state in (NOT_SCANNED, SCANNING):
        return "%s: listing its files..." % (job.name(),)
    if progress.state == DONE:
        return "%s: hashed ✓" % (job.name(),)
    text = "%s: %d%% hashed" % (job.name(), percent(progress))
    if not progress.is_started:
        text += " (paused)" if progress.is_paused else " (not hashing)"
    return text


def status_parts(jobs):
    """[(text, color)] of the jobs' statuses, for picker.status()"""
    parts = []
    for job in jobs:
        progress = job.progress()
        parts.append((status_text(job, progress), color(progress)))
    return parts


def bar(progress, width=20):
    """A bar of how far a job got: [██████░░░░░░░░░░░░░░]"""
    filled = width * percent(progress) // 100
    return '[%s%s]' % ('█' * filled, '░' * (width - filled))


def format_duration(seconds):
    """A duration for people: 45 s, 12 min, 3 h 20 min"""
    seconds = int(seconds)
    if seconds < 60:
        return "%d s" % (seconds,)
    if seconds < 3600:
        return "%d min" % (seconds // 60,)
    return "%d h %d min" % (seconds // 3600, seconds % 3600 // 60)


def time_left(progress):
    """How long the rest takes at its speed, or None if that isn't known"""
    if not progress.rate:
        return None
    return (progress.size - progress.size_done) / progress.rate
