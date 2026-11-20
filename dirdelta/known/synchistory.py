"""Each replica's sync history, kept in it (META_DIR/HISTORY_NAME, which the sync leaves out, as the rest of
META_DIR): a line of JSON a sync, appended once it's done, live only (a dry run changes nothing, this neither):
when, with which replica, and what it changed there. So a replica says itself when it was last synced, on any
computer (last_sync()), rather than only this one's config (replicas.py) or a log the user keeps
(replicalog.py)."""
import datetime
import json
import os

from dirdelta.drive.drivemeta import files as drive_files
from dirdelta.trees import paths
from dirdelta.util import dryrun

HISTORY_NAME = 'history.jsonl'
SYNC = 'sync'


def entry(other_path, other_name, changed, when=None):
    """A sync's record in a replica's history: when (now, if not given), with which replica (its path, and
    name), and what it changed in this one ('' for nothing: it was in step, or nothing was chosen)"""
    when = when or datetime.datetime.now().astimezone()
    return {'when': when.isoformat(timespec='seconds'), 'event': SYNC, 'with': other_path, 'withName': other_name,
            'changed': changed}


def record(path, item):
    """Append item (entry()'s) to the history of the replica at path (local, or a Drive one's cloud/... path).
    Nothing in a dry run. Raises OSError (or a Drive HttpError) if it can't be written."""
    if dryrun.DRYRUN:
        return
    line = json.dumps(item, ensure_ascii=False) + '\n'
    if paths.is_cloud_path(path):
        folder = paths.path_in_cloud(path)
        drive_files.write_text(folder, HISTORY_NAME, (drive_files.read_text(folder, HISTORY_NAME) or '') + line)
        return
    meta = os.path.join(path, paths.META_DIR)
    os.makedirs(meta, exist_ok=True)
    with open(os.path.join(meta, HISTORY_NAME), 'a', encoding='utf-8') as history:
        history.write(line)


def read(path):
    """The history of the replica at path, oldest first ([] if it has none). Raises OSError (or a Drive
    HttpError) if it can't be read."""
    if paths.is_cloud_path(path):
        text = drive_files.read_text(paths.path_in_cloud(path), HISTORY_NAME) or ''
    else:
        try:
            with open(os.path.join(path, paths.META_DIR, HISTORY_NAME), encoding='utf-8', errors='replace') as history:
                text = history.read()
        except FileNotFoundError:
            text = ''
    found = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def last_sync(path):
    """The replica's last sync's record (entry()'s), as it says itself, or None"""
    syncs = [item for item in read(path) if item.get('event') == SYNC]
    return syncs[-1] if syncs else None
