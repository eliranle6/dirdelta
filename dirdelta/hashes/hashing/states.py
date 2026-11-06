"""The hash a job makes, how it reads, and the states it goes through (Progress)"""
import collections


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
