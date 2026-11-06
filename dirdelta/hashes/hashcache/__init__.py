"""Local files' contents' hashes, kept in SQLite databases, so a file is read to hash it once: by
its path, with its size and modification time, which say whether it's still the same file (a hash
of a file that changed since isn't given). For a sync's or an inbox sort's comparing of contents
(see elsewhere.py), and for hashing whole replicas in the background (hashing.py). Kept from any
thread.

A local replica's files' hashes are kept in it, in META_DIR/META_NAME at its root (by their paths
in it, so they're found wherever its disk is mounted, on any machine), once use_replica() was
called for it: the database is made then (unless it's a dry run, or the replica is read-only), with
the hashes CACHE_FILE had of its files moved into it. Other files' (e.g. an inbox's that isn't in
the sorted tree, or a read-only replica's) are kept in CACHE_FILE, by their absolute paths.

SQLite rather than a JSON file: a whole replica's hashes (100k files) would be a file rewritten
whole each time it's saved, while a database writes only what changed. What's put is committed at
most every SAVE_INTERVAL seconds (and when dirdelta exits, see save()), so a crash loses at most
that much, which is hashed again next time.

Its parts are in the modules here; the names the rest of dirdelta uses are here too (but
CACHE_FILE, which is database's: set it there)."""
from dirdelta.hashes.hashcache.access import count_under, get, get_all, known_under, put  # noqa: F401
from dirdelta.hashes.hashcache.database import META_NAME, save  # noqa: F401
from dirdelta.hashes.hashcache.moving import move  # noqa: F401
from dirdelta.hashes.hashcache.replica_dbs import replica_file, use_replica, uses_replica  # noqa: F401
