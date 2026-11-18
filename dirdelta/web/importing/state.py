"""What the import page is sent of an import (import_state()): where its files come from (the phone's
name, the dir in it) and go, its overview, what's being done (reading the phone, checking or hashing
the replicas, moving), and its files by day, each with where the replicas have it and how sure that is"""
import datetime
import time

from dirdelta.known import replicanames
from dirdelta.phoneimport import applying, copying, overview, sources, suggest
from dirdelta.util import dryrun
from dirdelta.web import naming
from dirdelta.web.importing import checks as checking


def summary(found):
    return {'id': found.id, 'source': sources.describe(found.source), 'dest': found.dest, 'destName': naming.name(found.dest),
            'destDisk': replicanames.disk_name(found.dest),
            'otherDisk': found.dest_id is not None and found.dest_id != checking.identity(found.dest),
            'created': found.created, 'counts': found.counts()}


def import_state(found, check, with_files=True):
    """What the page shows of the import found, check being its replicas' (checks.Check): its overview,
    and its files by day (unless not with_files: the overview alone, as it's polled)"""
    files = found.files()
    known = check.known
    haves = {relpath: known.found(relpath, info['size'], info['sha1']) for relpath, info in files.items()} \
        if known is not None else None
    reading, moving = copying.reading_of(found.source), applying.applying_of(found.id)
    replica_paths = check.replica_paths
    state = dict(summary(found), label=list(dryrun.label()), checked=replica_paths, indexed=known is not None,
                 errors=(known.errors if known is not None else []) + check.errors,
                 checking={'busy': check.is_checking,
                           'ago': int(time.time() - check.checked_at) if check.checked_at else None},
                 replicas=[checking.replica_state(check, root) for root in replica_paths],
                 overview=overview.of(files, haves, replica_paths),
                 listedAgo=int(time.time() - found.pool.listed_at) if found.pool.listed_at else None,
                 reading={'phase': reading.phase, 'message': reading.message, 'asked': reading.nr_asked,
                          'copied': reading.nr_copied} if reading else None,
                 applying={'done': moving.is_done, 'lines': moving.lines} if moving else None)
    if with_files:
        state['folders'] = known.dirs.get(found.dest, []) if known is not None else []
        state['days'] = _days(files, haves, check.suggester)
    return state


def _days(files, haves, suggester):
    """The files by day (each with where the replicas have it, and how sure that is), and the dirs
    suggested for each day"""
    days = {}
    def by_day(item):
        # (The files without a date last)
        day = suggest.date_of(item[0], item[1]['mtime'])
        return day is None, day or datetime.date.min, item[0]
    for relpath, info in sorted(files.items(), key=by_day):
        have = [{'replica': replica, 'relpath': where, 'how': overview.match(info, how)}
                for replica, where, how in haves[relpath]] if haves is not None else None
        days.setdefault(str(suggest.date_of(relpath, info['mtime'])), []).append(dict(info, rel=relpath, have=have))
    return [{'day': day, 'files': day_files, 'suggested': suggester.suggest(_date(day)) if suggester else []}
            for day, day_files in days.items()]


def _date(text):
    """The date of a day's key (str(a date)), or None for the files without one"""
    return None if text == 'None' else datetime.date.fromisoformat(text)
