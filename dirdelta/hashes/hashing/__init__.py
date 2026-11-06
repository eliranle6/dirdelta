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
uses one of them at a time, since reading several files at once makes a disk seek between them.

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.hashes.hashing.job import Job  # noqa: F401
from dirdelta.hashes.hashing.registry import job, job_for, jobs  # noqa: F401
from dirdelta.hashes.hashing.pool import is_rotational, nr_workers, physical_cores  # noqa: F401
from dirdelta.hashes.hashing.states import (ALGORITHM, DONE, HASHING, NOT_SCANNED, SCANNED,  # noqa: F401
                                            SCANNING, Progress)
