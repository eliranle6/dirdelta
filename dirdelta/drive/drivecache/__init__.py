"""The cache of Google Drive's file list, an SQLite file (see database_path(), next to
LINES_FILE): a row per file or folder, by its id, with its parent and its metadata as the Drive API
gives it (a JSON object: id, name, parents, mimeType...), and My Drive's root folder's id. entries() reads
it into the paths of what's under a folder.

What dirdelta changes in Drive is added to it as it goes (add(), trash()), so it stays up to date. What's
under a folder is replaced with what Drive lists there now (replace_under()) when it's refreshed.

LINES_FILE is the format it was in before (and drivemeta.py's lines still are): one JSON line per file
or folder, after a line with the root's id, and a line {TRASHED_ID_KEY: id} per file trashed. If it's

Its parts are in the modules here; the names the rest of dirdelta uses are here too (but
LINES_FILE, which is names.LINES_FILE: set it there)."""
from dirdelta.drive.drivecache.changes import add, replace_under, trash, under  # noqa: F401
from dirdelta.drive.drivecache.database import changed_at, close, exists, rows  # noqa: F401
from dirdelta.drive.drivecache.metadata import (DriveCacheError, date_taken, hashes,  # noqa: F401
                                                is_google_file, modified_time, path_name, rfc3339)
from dirdelta.drive.drivecache.names import (FILE_FIELDS, FOLDER_MIME_TYPE, GOOGLE_APPS_MIME_PREFIX,  # noqa: F401
                                             HASH_FIELDS, ROOT_ID_KEY, TRASHED_ID_KEY)
from dirdelta.drive.drivecache.reading import Entry, count_under, entries, root_id  # noqa: F401
from dirdelta.drive.drivecache.stale import changing, mark_fresh, mark_stale, stale_paths, unmark_stale  # noqa: F401
from dirdelta.drive.drivecache.times import (note_updated, note_uploaded, note_user, updated,  # noqa: F401
                                             uploaded, user)
