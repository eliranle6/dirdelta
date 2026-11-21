"""The record each replica keeps of itself (META_DIR/RECORD_NAME, as its sync history is kept in it): an id of its
own, made once, and its name and look, so it says itself what it is, on any computer, for any user, rather than only
this one's file (replicas.py). dirdelta's file keeps, by the replica's label_key(), its id and what the two last both
had (Replicas.records): so it tells who changed what since. check() compares them:
- the replica has none: it's written (live only: a dry run writes nothing, as its history and hashes);
- dirdelta's file doesn't know the replica: its name and look are taken (it was named elsewhere);
- only dirdelta changed them: they're written to it;
- they were changed in the replica, not here (or both, otherwise): a disparity, for the user to settle (resolve());
- the replica's id isn't the one recorded: the record may be of another replica (a disparity too)."""
import collections
import datetime
import json
import os
import uuid

from dirdelta.drive.drivemeta import files as drive_files
from dirdelta.known import replicanames
from dirdelta.trees import paths
from dirdelta.util import dryrun

RECORD_NAME = 'replica.json'

# A disparity's kinds: the name or look differ (changed in the replica, or in both), or it's another replica's id
CHANGED, OTHER = 'changed', 'other'
# How a disparity's settled: the replica's taken here, or this file's written to it
TAKE_THEIRS, WRITE_MINE = 'theirs', 'mine'

# What check() found: whether the replica keeps its record now (kept), and the disparity, if any: {'kind', 'here':
# {'name', 'look'}, 'there': {'name', 'look', 'id'}, 'recordedId'}
Found = collections.namedtuple('Found', ['kept', 'disparity', 'why'], defaults=(None, ''))


def read(path):
    """The record the replica at path keeps of itself, or None. Raises OSError (or a Drive HttpError)."""
    if paths.is_cloud_path(path):
        text = drive_files.read_text(paths.path_in_cloud(path), RECORD_NAME)
    else:
        try:
            with open(os.path.join(path, paths.META_DIR, RECORD_NAME), encoding='utf-8') as record:
                text = record.read()
        except FileNotFoundError:
            text = None
    try:
        found = json.loads(text) if text else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def write(path, record):
    """Write the replica's record of itself; whether it was (not in a dry run). Raises OSError (or HttpError)."""
    if dryrun.DRYRUN:
        return False
    text = json.dumps(dict(record, updated=datetime.datetime.now().astimezone().isoformat(timespec='seconds')),
                      ensure_ascii=False, indent=2) + '\n'
    if paths.is_cloud_path(path):
        drive_files.write_text(paths.path_in_cloud(path), RECORD_NAME, text)
        return True
    meta = os.path.join(path, paths.META_DIR)
    os.makedirs(meta, exist_ok=True)
    temp = os.path.join(meta, RECORD_NAME + '.tmp')
    with open(temp, 'w', encoding='utf-8') as record:
        record.write(text)
    os.replace(temp, os.path.join(meta, RECORD_NAME))
    return True


def here(known, key):
    """{'name', 'look'} of the replica as dirdelta's file has them"""
    return {'name': known.labels.get(key), 'look': dict(known.looks.get(key) or {})}


def there(record):
    """{'name', 'look'} of the replica as its own record has them"""
    return {'name': record.get('name') or None, 'look': dict(record.get('look') or {})}


def check(path, known, record=None):
    """Compare the replica at path's record of itself with known's (a Replicas, changed but not saved), doing what
    needs no one (see above). record: what read() found, if it's been read. Returns a Found."""
    key = replicanames.label_key(path)
    mine, recorded = here(known, key), known.records.get(key)
    if record is None:
        record = read(path)
    if record is None:
        recorded = known.records.setdefault(key, {'id': uuid.uuid4().hex, 'agreed': mine})
        return _written(path, known, key, recorded['id'], mine)
    theirs = there(record)
    if recorded is None:
        # (Named elsewhere: taken, unless it's named otherwise here too, which the user settles)
        known.records[key] = {'id': record.get('id'), 'agreed': theirs}
        if mine['name'] is None and not mine['look']:
            _take(known, key, theirs)
            return Found(True)
        if mine != theirs:
            return Found(True, _disparity(CHANGED, mine, theirs, record, known.records[key]))
        return Found(True)
    if recorded.get('id') != record.get('id'):
        return Found(True, _disparity(OTHER, mine, theirs, record, recorded))
    if theirs == mine:
        recorded['agreed'] = mine
        return Found(True)
    if theirs == recorded.get('agreed'):
        # Changed here only: the replica's told
        return _written(path, known, key, recorded['id'], mine)
    return Found(True, _disparity(CHANGED, mine, theirs, record, recorded))


def resolve(path, known, how):
    """Settle the replica's disparity: TAKE_THEIRS (its name and look, and its id, taken here) or WRITE_MINE (this
    file's written to it, with the recorded id). Returns a Found (WRITE_MINE in a dry run: not kept, saying why)."""
    key, record = replicanames.label_key(path), read(path)
    if how == TAKE_THEIRS and record is not None:
        theirs = there(record)
        _take(known, key, theirs)
        known.records[key] = {'id': record.get('id'), 'agreed': theirs}
        return Found(True)
    recorded = known.records.setdefault(key, {'id': uuid.uuid4().hex, 'agreed': here(known, key)})
    return _written(path, known, key, recorded['id'], here(known, key))


def _written(path, known, key, record_id, mine):
    """Write mine to the replica (with record_id), noting it as agreed; a Found saying whether it was"""
    try:
        if not write(path, {'id': record_id, 'name': mine['name'], 'look': mine['look']}):
            return Found(False, None, "a dry run writes nothing to it")
    except OSError as error:
        return Found(False, None, "it can't be written: %s" % (error.strerror or error,))
    known.records[key]['agreed'] = mine
    return Found(True)


def _take(known, key, theirs):
    known.set_label(key, theirs['name'])
    known.set_look(key, theirs['look'].get('color'), theirs['look'].get('icon'))


def _disparity(kind, mine, theirs, record, recorded):
    return {'kind': kind, 'here': mine, 'there': dict(theirs, id=record.get('id'), updated=record.get('updated')),
            'recordedId': recorded.get('id')}
