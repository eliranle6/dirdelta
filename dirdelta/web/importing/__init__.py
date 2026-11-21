"""The import page's API (routes()): the imports and the phones plugged in, starting one (one for each
source and replica), an import's overview and files by day (by name and size first, by contents once
copied and hashed), their thumbnails and files, copying and hashing them, the dirs chosen for them,
moving them in, ending it; and comparing better: checking the replicas again, hashing one, reading a
Drive one again (see phoneimport/, and checks.py)"""
import os

from dirdelta.phoneimport import applying, copying, sources, store, thumbs
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.trees import paths
from dirdelta.web import naming
from dirdelta.util import dryrun
from dirdelta.web.importing import checks as checking
from dirdelta.web.importing.state import import_state, note_where, summary
from dirdelta.web.server import FileReply, Reply


# The replicas' checks, each import's destination's (shared by the pages: see checks.py)
CHECKS = checking.Checks()


def inboxes():
    """[{'path', 'name', 'kind' (phone, newphone: plugged in but not one of the user's, drive, folder), 'there',
    'added' (an inbox of the user's: it can be forgotten), 'phone' (a phone's id, sources.phone_id()), 'source'
    (sources.describe()), 'dests' (the replicas its files may go into, the likeliest first), 'imports' (its imports'
    summaries)}]: the user's phones (each storage plugged in, else where an import of it was, else the phone itself),
    the phones plugged in that aren't theirs, then their inboxes, and any other source an import of theirs has"""
    known_replicas = replicas.load()
    imports = store.all_imports()
    phones = _phones(known_replicas, imports)
    found = {}
    plugged = sources.phones()
    for phone, info in phones.items():
        storages = [path for _, path in plugged if sources.phone_id(path) == phone]
        for path in storages:
            found[path] = ('phone', info['name'], True)
        if not storages:
            # (Unplugged: where its imports were from, else the phone itself)
            for path in [one.source for one in imports if sources.phone_id(one.source) == phone] or [_phone_path(phone)]:
                found.setdefault(path, ('phone', info['name'], False))
    for name, path in plugged:
        found.setdefault(path, ('newphone', name, True))
    added = known_replicas.inbox_paths()
    for path in added:
        # (An inbox by its label, else its folder's own name: "unsorted", not its disk's)
        found.setdefault(path, ('drive' if paths.is_cloud_path(path) else 'folder', replicanames.label(path) or os.path.basename(path.rstrip('/')),
                                paths.is_cloud_path(path) or os.path.isdir(path)))
    for one in imports:
        # (Which of its files the replicas have: checked again when due, in the background, and kept)
        note_where(one, CHECKS.get(one.dest))
        described = sources.describe(one.source)
        found.setdefault(one.source, ('phone' if described['device'] else 'drive' if described['drive'] else 'folder',
                                      described['device'] or naming.name(one.source),
                                      paths.is_cloud_path(one.source) or os.path.isdir(one.source)))
    return [{'path': path, 'kind': kind, 'name': name, 'there': there, 'added': path in added,
             'phone': sources.phone_id(path), 'source': sources.describe(path),
             # (An unsorted folder's: how many files its sorts took out of it, and how many it has now)
             'sorting': _sorting(path, known_replicas) if kind in ('drive', 'folder') else None,
             'dests': checking.destinations(path) if kind != 'newphone' else [],
             'imports': [summary(one) for one in imports if one.source == path]}
            for path, (kind, name, there) in found.items()]


def _sorting(path, known_replicas):
    """{'sorted': how many files the inbox's sorts took out of it, 'left': how many it has now (None if that can't be
    told: not there), 'when': when it was last sorted}"""
    counts = known_replicas.inbox_counts.get(path) or {}
    return {'sorted': counts.get('sorted', 0), 'left': _nr_files(path), 'when': counts.get('when')}


def _nr_files(path):
    """How many files the inbox at path has now (a Drive one's as the cache has them), or None if it can't be read"""
    try:
        if paths.is_cloud_path(path):
            from dirdelta.drive import drivecache
            return sum(1 for entry in drivecache.entries(paths.path_in_cloud(path)) if not entry.is_dir)
        if not os.path.isdir(path):
            return None
        return sum(len(files) for _, _, files in os.walk(path))
    except Exception:
        return None


def _phones(known_replicas, imports):
    """The user's phones ({id: {'name'}}): the file's; once, a file from before has those its imports were from"""
    if known_replicas.phones is None:
        for one in imports:
            phone = sources.phone_id(one.source)
            if phone and phone not in (known_replicas.phones or {}):
                known_replicas.add_phone(phone, sources.describe(one.source)['device'])
        known_replicas.phones = known_replicas.phones or {}
        replicas.save(known_replicas)
    return known_replicas.phones


def _phone_path(phone):
    """Where a phone of the user's that isn't plugged in, nor imported from yet, is said to be: its USB link's mount"""
    return os.path.join(sources.GVFS_DIR, sources.MTP_PREFIX + phone)


def routes():
    checks = CHECKS

    def listing(query, body):
        from dirdelta.drive import freshening
        known_replicas = replicas.load()
        # (Drive's lists of the user's replicas and inboxes over a day old read again, in the background)
        freshening.refresh_stale(known_replicas.replica_paths() + known_replicas.inbox_paths())
        return {'inboxes': inboxes(), 'label': list(dryrun.label())}

    def add_phone(query, body):
        """One of the user's phones from now on, or its name changed: body['phone'] (its id), body['name']"""
        phone, name = (body.get('phone') or '').strip(), (body.get('name') or '').strip()
        if not phone or not name:
            return {'ok': False, 'error': "Give it a name."}
        known_replicas = replicas.load()
        known_replicas.add_phone(phone, name)
        replicas.save(known_replicas)
        return {'ok': True}

    def remove_phone(query, body):
        """Not one of the user's phones any more (body['phone']): not while an import of it is kept"""
        phone = body.get('phone') or ''
        if any(sources.phone_id(one.source) == phone for one in store.all_imports()):
            return {'ok': False, 'error': "End its imports first (each on its page)."}
        known_replicas = replicas.load()
        known_replicas.remove_phone(phone)
        replicas.save(known_replicas)
        return {'ok': True}

    def new(query, body):
        source, dest = body.get('source', ''), body.get('dest', '')
        # (A phone's: only one of the user's, added first)
        phone = sources.phone_id(source)
        if phone and phone not in (replicas.load().phones or {}):
            return {'error': "Add this phone first."}
        if not paths.is_cloud_path(source):
            source = os.path.abspath(source) if source else ''
            if not os.path.isdir(source):
                return {'error': "Not a folder: %s" % (source,)}
        if dest not in [found['path'] for found in checking.destinations(source)]:
            return {'error': "Not a replica it can go into: %s" % (dest,)}
        found = store.create(source, dest, checking.identity(dest))
        copying.read(found.source)
        checks.get(found.dest)
        return {'id': found.id}

    def state(query, body):
        found = store.load(query.get('id'))
        if found is None:
            return {'error': 'No such import'}
        return import_state(found, checks.get(found.dest), with_files=query.get('files') != '0')

    def thumb(query, body):
        found, relpath = store.load(query.get('id')), query.get('rel', '')
        data = thumbs.jpeg(found.pool, relpath) if found is not None and _is_inside(relpath) else None
        return Reply(data, 'image/jpeg', is_kept=True) if data else Reply(b'', 'text/plain', 404)

    def file(query, body):
        found, relpath = store.load(query.get('id')), query.get('rel', '')
        path = found.pool.readable_path(relpath) if found is not None and _is_inside(relpath) else None
        return FileReply(path) if path else Reply(b'', 'text/plain', 404)

    def assign(query, body):
        found = store.load(body.get('id'))
        if found is None:
            return {'ok': False}
        target = body.get('target')
        target = target.strip('/') if target and _is_inside(target) else None
        found.choose(body.get('rels', []), target, bool(body.get('skip')))
        return {'ok': True}

    def read(query, body):
        """List the source again, or copy and hash its files: 'all' not hashed, or 'nameOnly' (the ones a
        replica has by name and size only)"""
        found = store.load(body.get('id'))
        if found is None:
            return {'ok': False}
        which = body.get('which')
        files = found.files()
        if which == 'list':
            copying.read(found.source, from_drive=True)
            return {'ok': True}
        relpaths = [relpath for relpath, info in files.items() if not info['sha1'] and info['state'] != store.MOVED]
        if which == 'nameOnly':
            check = checks.get(found.dest)
            relpaths = [relpath for relpath in relpaths if check.known is not None and
                        check.known.found(relpath, files[relpath]['size'])]
        copying.read(found.source, is_listing=False, relpaths=relpaths)
        return {'ok': True}

    def apply(query, body):
        found = store.load(body.get('id'))
        if found is None:
            return {'ok': False}
        if found.dest_id is not None and found.dest_id != checking.identity(found.dest):
            return {'ok': False, 'error': "Another disk is at %s now: not this import's replica." % (found.dest,)}
        applying.apply(found)
        return {'ok': True}

    def end(query, body):
        found = store.load(body.get('id'))
        if found is None:
            return {'ok': False}
        reading, moving = copying.reading_of(found.source), applying.applying_of(found.id)
        if (reading is not None and reading.phase in ('listing', 'copying')) or (moving is not None and not moving.is_done):
            return {'ok': False, 'error': "It's being read or moved: wait for that to end."}
        found.end()
        return {'ok': True}

    def recheck(query, body):
        found = store.load(body.get('id'))
        if found is None:
            return {'ok': False}
        replica = body.get('replica')
        if replica and replica in checks.get(found.dest).replica_paths:
            if body.get('how') == 'hash' and not paths.is_cloud_path(replica):
                checks.hash(found.dest, replica)
            elif body.get('how') == 'drive' and paths.is_cloud_path(replica):
                checks.read_drive(found.dest, replica)
        else:
            checks.recheck(found.dest)
        return {'ok': True}

    return {('GET', '/api/imports'): listing, ('POST', '/api/imports/new'): new, ('GET', '/api/import'): state,
            ('GET', '/api/import/thumb'): thumb, ('GET', '/api/import/file'): file,
            ('POST', '/api/import/assign'): assign, ('POST', '/api/import/read'): read,
            ('POST', '/api/import/apply'): apply, ('POST', '/api/import/end'): end,
            ('POST', '/api/import/recheck'): recheck, ('POST', '/api/phones/add'): add_phone,
            ('POST', '/api/phones/remove'): remove_phone}


def _is_inside(relpath):
    return not os.path.isabs(relpath) and '..' not in relpath.split('/')
