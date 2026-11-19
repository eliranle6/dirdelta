"""The import page's API (routes()): the imports and the phones plugged in, starting one (one for each
source and replica), an import's overview and files by day (by name and size first, by contents once
copied and hashed), their thumbnails and files, copying and hashing them, the dirs chosen for them,
moving them in, ending it; and comparing better: checking the replicas again, hashing one, reading a
Drive one again (see phoneimport/, and checks.py)"""
import os

from dirdelta.phoneimport import applying, copying, sources, store, thumbs
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
    """[{'path', 'name', 'kind' (phone, drive, folder), 'there', 'added' (one of the user's, not a phone
    plugged in: it can be forgotten), 'source' (sources.describe()), 'dests' (the replicas its files
    may go into, the likeliest first), 'imports' (its imports' summaries)}]: the user's inboxes, the
    phones plugged in first, and any other source an import of theirs has (e.g. a phone unplugged)"""
    added = replicas.load().inbox_paths()
    found = {path: ('phone', name, True) for name, path in sources.phones()}
    for path in added:
        found.setdefault(path, ('drive' if paths.is_cloud_path(path) else 'folder', naming.name(path),
                                paths.is_cloud_path(path) or os.path.isdir(path)))
    imports = store.all_imports()
    for one in imports:
        # (Which of its files the replicas have: checked again when due, in the background, and kept)
        note_where(one, CHECKS.get(one.dest))
        described = sources.describe(one.source)
        found.setdefault(one.source, ('phone' if described['device'] else 'drive' if described['drive'] else 'folder',
                                      described['device'] or naming.name(one.source),
                                      paths.is_cloud_path(one.source) or os.path.isdir(one.source)))
    return [{'path': path, 'kind': kind, 'name': name, 'there': there, 'added': path in added,
             'source': sources.describe(path), 'dests': checking.destinations(path),
             'imports': [summary(one) for one in imports if one.source == path]}
            for path, (kind, name, there) in found.items()]


def routes():
    checks = CHECKS

    def listing(query, body):
        from dirdelta.drive import freshening
        known_replicas = replicas.load()
        # (Drive's lists of the user's replicas and inboxes over a day old read again, in the background)
        freshening.refresh_stale(known_replicas.replica_paths() + known_replicas.inbox_paths())
        return {'inboxes': inboxes(), 'label': list(dryrun.label())}

    def new(query, body):
        source, dest = body.get('source', ''), body.get('dest', '')
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
            ('POST', '/api/import/recheck'): recheck}


def _is_inside(relpath):
    return not os.path.isabs(relpath) and '..' not in relpath.split('/')
