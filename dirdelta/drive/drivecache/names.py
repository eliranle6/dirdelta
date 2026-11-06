"""Where the cache is, and the names and fields of what it keeps"""
import os


LINES_FILE = os.path.expanduser('~/.cache/dirdelta/files.txt')

FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'
# Google's own types (Docs, Sheets, Slides, shortcuts, ...): not files, so they can't be downloaded
# (only exported to another format), but they're in Drive's folders, so they're in the tree
GOOGLE_APPS_MIME_PREFIX = 'application/vnd.google-apps.'
# What's added to a Google file's name in its path, so it's told from a file, as Google Drive for
# desktop names them on disk (a Google Sheet "Budget" is Budget.gsheet), by its mimeType's last part.
# Others get ".g" and that part.
GOOGLE_FILE_EXTENSIONS = {
    'document': '.gdoc',
    'spreadsheet': '.gsheet',
    'presentation': '.gslides',
    'drawing': '.gdraw',
    'form': '.gform',
    'shortcut': '.glink',
}
# The key of the cache's line with My Drive's root folder's id
ROOT_ID_KEY = 'myDriveRootId'
# The key of a line with the id of a file that dirdelta moved to the trash since the scan
TRASHED_ID_KEY = 'trashedId'
# The fields of a file or folder that the cache has, for the Drive API
FILE_FIELDS = ('id, name, parents, kind, size, mimeType, modifiedTime, sha1Checksum, sha256Checksum, '
               'imageMediaMetadata(time)')
# The hashes of a file's contents that Drive gives, by their hashlib names: the fastest to work out
# first (SHA-1 is about twice as fast as SHA-256), for comparing with a local file
HASH_FIELDS = (('sha1', 'sha1Checksum'), ('sha256', 'sha256Checksum'))

# How many of the names to fix an error lists
MAX_PROBLEMS_SHOWN = 20
