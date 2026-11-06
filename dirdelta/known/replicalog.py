"""Each replica's log of changes, LOG_NAME at its root, which the user keeps, newest last:

    15.12.2025 - copied DCIM pictures from old pixel 8 (not whatsapp pictures)
    17.05.2026 - removed old money.ods
                 remove Resume.* files

(an entry a line starting with its date, DD.MM.YYYY, then ' - ' and what changed; its other lines
after it; an early entry may be a bare date). dirdelta reads it when it syncs a replica, keeps its
last entry (with when it saw the replica, and when it last changed it: see replicas.py's known),
shows it, and after a sync that changed a replica, offers to add an entry to it.

A replica is known by its identity(), not its path: a local one by the filesystem it's on (its
UUID, see mounts.py) and the path in it, so a disk is the same replica wherever it's mounted

What a sync changed, and the entries offered for it, are in log_entries.py."""
import collections
import datetime
import os
import re
import tempfile

from googleapiclient.errors import HttpError

from dirdelta.drive import clouddirtree
from dirdelta.known import mounts
from dirdelta.known import replicanames
from dirdelta.trees import paths
from dirdelta.util import downloads


LOG_NAME = 'last_update.txt'
# An entry's first line: its date (DD.MM.YYYY), and what changed after a '-'
_ENTRY_LINE = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:-\s*(.*))?$')
DATE_FORMAT = '%d.%m.%Y'

# An entry of a log: its date (a datetime.date, or None for lines before the first dated one, or
# with a date that isn't one), and its text (its lines, without the date, joined by '\n')
Entry = collections.namedtuple('Entry', ['date', 'text'])


def parse(text):
    """The entries of a log's text, in its order (the newest last). Lines it can't parse are kept
    as text: in the entry before them, or an undated one at the start."""
    found = []
    for line in text.splitlines():
        match = _ENTRY_LINE.match(line.strip())
        date = None
        if match is not None:
            try:
                date = datetime.date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            except ValueError:
                pass
        if match is not None and date is not None:
            found.append(Entry(date, (match.group(4) or '').strip()))
        elif line.strip():
            if found:
                previous = found[-1]
                found[-1] = Entry(previous.date, '\n'.join(part for part in (previous.text, line.strip()) if part))
            else:
                found.append(Entry(None, line.strip()))
    return found


def last_entry(text):
    """The newest dated entry of a log's text (the last one, or the latest date, if they're out of
    order), or None if it has none"""
    dated = [entry for entry in parse(text) if entry.date is not None]
    if not dated:
        return None
    latest = max(entry.date for entry in dated)
    return [entry for entry in dated if entry.date == latest][-1]


def entry_line(date, text):
    """An entry's line, as the log has them: 'DD.MM.YYYY - text'"""
    return "%s - %s" % (date.strftime(DATE_FORMAT), text)


def with_entry(text, line):
    """A log's text with the entry line added at its end"""
    if text and not text.endswith('\n'):
        text += '\n'
    return text + line + '\n'


# The replica at a path's identity (see the module's doc), a string
identity = replicanames.identity


def disk_uuid(replica_identity):
    """The UUID of the filesystem a local replica is on, by its identity, or None"""
    if replica_identity.startswith('uuid:'):
        return replica_identity.split(':', 2)[1]
    return None


def is_disk_connected(replica_identity):
    """Whether the disk a local replica is on is connected (True if it isn't known by a disk)"""
    uuid = disk_uuid(replica_identity)
    return uuid is None or os.path.exists(os.path.join(mounts.names.BY_UUID_DIR, uuid))


def read(tree):
    """The text of the log of the replica whose tree it is (a DirTree, local or Drive's), or None if
    it has none, or it can't be read. A Drive one is downloaded (or found downloaded, see
    downloads.py)."""
    try:
        if isinstance(tree, clouddirtree.CloudDirTree):
            if not tree.has_file(LOG_NAME):
                return None
            local_path = downloads.get(paths.join(tree.displayname(), LOG_NAME), tree.file_size(LOG_NAME),
                                       lambda path: tree.fetch_file(LOG_NAME, path))
        else:
            local_path = os.path.join(tree.fullpath(), LOG_NAME)
        with open(local_path, encoding='utf-8', errors='replace') as log:
            return log.read()
    except (OSError, HttpError):
        return None


def write(tree, text):
    """Make the log of the replica whose tree it is (local or Drive's) text, in its place. Raises
    OSError (or HttpError) if it can't be written."""
    if isinstance(tree, clouddirtree.CloudDirTree):
        with tempfile.TemporaryDirectory(prefix='dirdelta-log-') as temp_dir:
            local_path = os.path.join(temp_dir, LOG_NAME)
            with open(local_path, 'w', encoding='utf-8') as log:
                log.write(text)
            tree.write_file(LOG_NAME, local_path)
        return
    path = os.path.join(tree.fullpath(), LOG_NAME)
    temp_path = path + '.dirdelta-tmp'
    with open(temp_path, 'w', encoding='utf-8') as log:
        log.write(text)
    os.replace(temp_path, path)
