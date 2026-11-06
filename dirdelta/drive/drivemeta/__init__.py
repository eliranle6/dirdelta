"""A Drive replica's file list, kept in it too: FILE_NAME in its paths.META_DIR (cloud/X/meta/
files.jsonl), so another machine (or this one, with an older cache) can use it rather than read
the whole folder from Drive again. Its first line is a header (HEADER_KEY: the folder's path, its
id, My Drive's root id), then a line per file and folder under it, as the cache has them
(drivecache.py), without what's in META_DIR.

At a sync's (or a sort's) start, check() asks Drive (two requests) for the copy's modifiedTime: if
it's newer than when this machine's cache of the folder was last updated (drivecache.updated()),
and not the copy this cache made, it's downloaded into the cache. While the sync goes on, an
Uploader uploads the cache's list again whenever it changed since (every UPLOAD_INTERVAL seconds at
most, on a thread of its own, and once more when the sync ends): not after each change (each would
be an upload of the whole list), and not left for a question at the end, which a sync cut off would
never get to. Nothing is uploaded in a dry run.

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.drive.drivemeta.checking import check  # noqa: F401
from dirdelta.drive.drivemeta.names import FILE_NAME, HEADER_KEY, USED  # noqa: F401
from dirdelta.drive.drivemeta.uploader import Uploader, kept  # noqa: F401
from dirdelta.drive.drivemeta.uploading import upload  # noqa: F401
