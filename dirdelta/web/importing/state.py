"""What the import page is sent of an import (import_state()): where its files come from (the phone's
name, the dir in it) and go, its overview, what's being done (reading the phone, checking or hashing
the replicas, moving), and its files by day, each with where the replicas have it and how sure that is"""
import datetime
import os
import time

from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.phoneimport import applying, copying, known, overview, removing, sources, store, suggest
from dirdelta.util import dryrun
from dirdelta.web import naming
from dirdelta.web.importing import checks as checking


def described(source):
    """sources.describe(source), a phone called by the name the user gave it"""
    found = sources.describe(source)
    named = ((replicas.load().phones or {}).get(sources.phone_id(source)) or {}).get('name')
    if found['device'] and named:
        found['device'] = named
    return found


def summary(found):
    files = found.files()
    counts = {store.PENDING: 0, store.COPIED: 0, store.MOVED: 0, store.SKIPPED: 0}
    for info in files.values():
        counts[info['state']] += 1
    return {'id': found.id, 'source': described(found.source), 'dest': found.dest, 'destName': naming.name(found.dest),
            'destDisk': replicanames.disk_name(found.dest),
            'otherDisk': found.dest_id is not None and found.dest_id != checking.identity(found.dest),
            'created': found.created, 'changed': _changed(found), 'counts': counts, 'already': already(found, files)}


def already(found, files):
    """{'contents', 'name', 'checked'}: how many of the files not sorted yet (not moved or skipped) a
    replica has, by their contents and by their name and size only, as of when that was last checked
    (where()); None if it never was"""
    where = found.where()
    if where is None:
        return None
    left = [relpath for relpath, info in files.items() if info['state'] in (store.PENDING, store.COPIED)]
    hows = [where['files'].get(relpath) for relpath in left]
    return {'contents': hows.count(store.THERE_CONTENTS), 'name': hows.count(store.THERE_NAME), 'checked': where.get('checked')}


def note_where(found, check, files=None, haves=None):
    """Keep which of the import's files check's replicas have (found.remember_where()), once it's done"""
    if check.known is None or check.checked_at is None:
        return
    files = files if files is not None else found.files()
    if haves is None:
        haves = {relpath: check.known.found(relpath, info['size'], info['sha1']) for relpath, info in files.items()}
    where = {}
    for relpath, places in haves.items():
        if places:
            where[relpath] = store.THERE_CONTENTS if any(how == known.SAME_CONTENTS for _, _, how in places) else store.THERE_NAME
    found.remember_where(where, datetime.datetime.fromtimestamp(check.checked_at).strftime('%Y-%m-%d %H:%M'))


def _changed(found):
    """When the import's choices were last saved (a file sorted, or skipped), 'YYYY-MM-DD HH:MM'"""
    try:
        stamp = os.path.getmtime(os.path.join(found.folder, store.MANIFEST))
    except OSError:
        stamp = found.created
    return datetime.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M')


def import_state(found, check, with_files=True):
    """What the page shows of the import found, check being its replicas' (checks.Check): its overview,
    and its files by day (unless not with_files: the overview alone, as it's polled)"""
    files = found.files()
    known = check.known
    haves = {relpath: known.found(relpath, info['size'], info['sha1']) for relpath, info in files.items()} \
        if known is not None else None
    if haves is not None:
        note_where(found, check, files, haves)
    reading, moving, removed = copying.reading_of(found.source), applying.applying_of(found.id), removing.removing_of(found.id)
    replica_paths = check.replica_paths
    state = dict(summary(found), label=list(dryrun.label()), checked=replica_paths, indexed=known is not None,
                 # (The replicas it could go into instead: each another import, chosen on its page)
                 dests=[{'path': dest['path'], 'name': dest['name']} for dest in checking.destinations(found.source)],
                 errors=(known.errors if known is not None else []) + check.errors,
                 checking={'busy': check.is_checking,
                           'ago': int(time.time() - check.checked_at) if check.checked_at else None},
                 replicas=[checking.replica_state(check, root) for root in replica_paths],
                 overview=overview.of(files, haves, replica_paths),
                 listedAgo=int(time.time() - found.pool.listed_at) if found.pool.listed_at else None,
                 reading={'phase': reading.phase, 'message': reading.message, 'asked': reading.nr_asked,
                          'copied': reading.nr_copied} if reading else None,
                 applying={'done': moving.is_done, 'lines': moving.lines, 'total': moving.nr_total, 'count': moving.nr_done,
                           'moves': found.pool.is_drive, 'moved': moving.nr_moved, 'started': moving.started} if moving else None,
                 removing={'done': removed.is_done, 'lines': removed.lines, 'total': removed.nr_total, 'count': removed.nr_done,
                           'removed': removed.nr_removed, 'started': removed.started} if removed else None)
    if with_files:
        state['folders'] = known.dirs.get(found.dest, []) if known is not None else []
        # (The folders files were last put in, the latest first: offered at once, kept across imports and the file sort)
        state['recentDirs'] = replicas.load().dirs_of(found.dest)
        state['groups'] = _groups(found.source, files, haves, check.suggester)
    return state


def _groups(source, files, haves, suggester):
    """The files in their groups (sources.group_of(): a phone's camera's, WhatsApp's images, its videos), each with the
    dirs suggested for it all (where the replica keeps its kind), and in it by day (each file with where the replica
    has it, and how sure that is, and the dirs suggested for the day)"""
    groups = {}

    def by_day(item):
        # (The files without a date last)
        day = suggest.date_of(item[0], item[1]['mtime'])
        return day is None, day or datetime.date.min, item[0]
    for relpath, info in sorted(files.items(), key=by_day):
        have = [{'replica': replica, 'relpath': where, 'how': overview.match(info, how)}
                for replica, where, how in haves[relpath]] if haves is not None else None
        days = groups.setdefault(sources.group_of(source, relpath), {})
        days.setdefault(str(suggest.date_of(relpath, info['mtime'])), []).append(dict(info, rel=relpath, have=have))
    order = list(sources.GROUP_TITLES)
    return [{'key': key, 'title': sources.GROUP_TITLES[key], 'suggested': suggester.suggest_group(key) if suggester else [],
             'days': [{'day': day, 'files': day_files, 'suggested': suggester.suggest(_date(day)) if suggester else []}
                      for day, day_files in days.items()]}
            for key, days in sorted(groups.items(), key=lambda item: order.index(item[0]))]


def _date(text):
    """The date of a day's key (str(a date)), or None for the files without one"""
    return None if text == 'None' else datetime.date.fromisoformat(text)
