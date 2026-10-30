"""Each replica's log of changes, LOG_NAME at its root, which the user keeps, newest last:

    15.12.2025 - copied DCIM pictures from old pixel 8 (not whatsapp pictures)
    17.05.2026 - removed old money.ods
                 remove Resume.* files

(an entry a line starting with its date, DD.MM.YYYY, then ' - ' and what changed; its other lines
after it; an early entry may be a bare date). dirdelta reads it when it syncs a replica, keeps its
last entry (with when it saw the replica, and when it last changed it: see replicas.py's known),
shows it, and after a sync that changed a replica, offers to add an entry to it.

A replica is known by its identity(), not its path: a local one by the filesystem it's on (its
UUID, see mounts.py) and the path in it, so a disk is the same replica wherever it's mounted; a
Drive one by My Drive's root id and its path."""
import collections
import datetime
import os
import re
import tempfile

from dirdelta import clouddirtree
from dirdelta import downloads
from dirdelta import drivecache
from dirdelta import dryrun
from dirdelta import mounts
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicas

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


def identity(path):
    """The replica at path's identity (see the module's doc), a string"""
    if paths.is_cloud_path(path):
        return 'drive:%s:/%s' % (drivecache.root_id() or '?', '/'.join(paths.components(path)[1:]))
    path = os.path.realpath(path)
    mount = mounts.current_mount(path)
    if mount is not None and mount.uuid:
        relpath = os.path.relpath(path, mount.target)
        return 'uuid:%s:/%s' % (mount.uuid, '' if relpath == '.' else relpath)
    return 'path:%s' % (path,)


def disk_uuid(replica_identity):
    """The UUID of the filesystem a local replica is on, by its identity, or None"""
    if replica_identity.startswith('uuid:'):
        return replica_identity.split(':', 2)[1]
    return None


def is_disk_connected(replica_identity):
    """Whether the disk a local replica is on is connected (True if it isn't known by a disk)"""
    uuid = disk_uuid(replica_identity)
    return uuid is None or os.path.exists(os.path.join(mounts.BY_UUID_DIR, uuid))


def read(tree):
    """The text of the log of the replica whose tree it is (a DirTree, local or Drive's), or None if
    it has none, or it can't be read. A Drive one is downloaded (or found downloaded, see
    downloads.py)."""
    try:
        if isinstance(tree, clouddirtree.CloudDirTree):
            if not tree.has_file(LOG_NAME):
                return None
            local_path = downloads.get(posix_join(tree.displayname(), LOG_NAME), tree.file_size(LOG_NAME),
                                       lambda path: tree.fetch_file(LOG_NAME, path))
        else:
            local_path = os.path.join(tree.fullpath(), LOG_NAME)
        with open(local_path, encoding='utf-8', errors='replace') as log:
            return log.read()
    except (OSError, clouddirtree.HttpError):
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


def posix_join(cloud_path, name):
    return cloud_path.rstrip('/') + '/' + name


class Changes(object):
    """What a sync or an inbox's sort changed in each replica (live, not in a dry run), by its path,
    for an entry of its log: how many files were copied into it (from where), removed from it, moved
    in it, or moved out of it (to where)"""
    def __init__(self):
        # {path: {(verb, 'from' or 'to', where, or None): how many files}}, in the order they came
        self._counts = collections.OrderedDict()

    def note(self, path, verb, count, place=None, preposition='from'):
        """Note that count files were copied (verb 'copied', from place), 'removed' or 'moved' (to
        place, with preposition 'to') in the replica at path"""
        if count:
            counts = self._counts.setdefault(path, collections.OrderedDict())
            key = (verb, preposition if place else None, place)
            counts[key] = counts.get(key, 0) + count

    def paths(self):
        """The paths of the replicas changed, in the order they were"""
        return list(self._counts)

    def summary(self, path):
        """What changed in the replica at path, as an entry's text, e.g. 'copied 12 files from
        cloud/eliran; removed 3 files' ('' if nothing)"""
        return '; '.join("%s %s%s" % (verb, "1 file" if count == 1 else "%d files" % (count,),
                                      " %s %s" % (preposition, place) if place else "")
                         for (verb, preposition, place), count in self._counts.get(path, {}).items())

def note_seen(replicas_and_paths, known_replicas):
    """Note in known_replicas (a replicas.Replicas; not saved) that the replicas of replicas_and_paths
    ([(tree, path)]) are being synced or sorted now, with their logs' last entries"""
    now = datetime.datetime.now()
    for tree, path in replicas_and_paths:
        text = read(tree)
        known_replicas.note_seen(identity(path), path, last_entry(text) if text else None, now)


# The choices for adding an entry to a changed replica's log (what each does first, the path last,
# so a long one doesn't hide it)
NO_ENTRY = "No"
ADD_ENTRY = "Add it to its %s (%s)"
EDIT_ENTRY = "Edit it first"


def offer_entries(changes, replicas_and_paths, known_replicas):
    """After a sync or an inbox's sort, for each replica it changed (changes, a Changes: what was
    copied into it, removed from it, moved in it), offer to add an entry saying so to its log
    (only its: the other replica's log is of the other's changes), today's: e.g. '30.10.2026 -
    copied 12 files from cloud/eliran'. replicas_and_paths: [(the replica's tree, whose
    displayname() changes has it by, its path)]. Notes in known_replicas (a replicas.Replicas,
    saved) when each was changed, and its log's last entry."""
    today = datetime.date.today()
    by_name = {tree.displayname(): (tree, path) for tree, path in replicas_and_paths}
    for name in changes.paths():
        tree, path = by_name[name]
        text = changes.summary(name)
        known_replicas.note_changed(identity(path), datetime.datetime.now())
        while True:
            line = entry_line(today, text)
            add = ADD_ENTRY % (LOG_NAME, path)
            header = "Add what was done to the log (%s) of %s?\n  %s" % (LOG_NAME, path, line)
            answer = picker.pick_option([NO_ENTRY, add, EDIT_ENTRY], header=header)
            if answer == EDIT_ENTRY:
                edited = messages.ask("The entry of %s's %s" % (path, LOG_NAME),
                                      ["What changed in %s (after its date, %s):" % (
                                          path, today.strftime(DATE_FORMAT))],
                                      "> ", text, dryrun.label())
                text = edited or text
                continue
            if answer == add:
                _add_entry(tree, path, line, Entry(today, text), known_replicas)
            break
    if changes.paths():
        replicas.save(known_replicas)


def _add_entry(tree, path, line, entry, known_replicas):
    """Add line (an entry) to the log of the replica at path (tree), made if it has none"""
    try:
        write(tree, with_entry(read(tree) or '', line))
    except (OSError, clouddirtree.HttpError) as error:
        messages.show("Cannot add the entry to %s's %s" % (path, LOG_NAME), [str(error)], dryrun.label(), 'red')
        return
    known_replicas.note_entry(identity(path), entry)

