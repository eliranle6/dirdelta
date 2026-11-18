"""The import page's API (routes()): the imports and the phones plugged in, starting one (one for each
source and replica), an import's overview and files by day (by name and size first, by contents once
copied and hashed), their thumbnails and files, copying and hashing them, the dirs chosen for them,
moving them in, ending it; and comparing better: checking the replicas again, hashing one, reading a
Drive one again (see phoneimport/, and checks.py)"""
import os

from dirdelta.phoneimport import applying, copying, sources, store, thumbs
from dirdelta.trees import paths
from dirdelta.util import dryrun
from dirdelta.web.importing import checks as checking
from dirdelta.web.importing.state import import_state, summary
from dirdelta.web.server import FileReply, Reply


def routes():
    checks = checking.Checks()

    def listing(query, body):
        dests, default = checking.destinations()
        return {'imports': [summary(found) for found in store.all_imports()],
                'phones': [dict(sources.describe(path), name=name, path=path) for name, path in sources.phones()],
                'dests': dests, 'defaultDest': default, 'label': list(dryrun.label())}

    def new(query, body):
        source, dest = body.get('source', ''), body.get('dest', '')
        if not os.path.isdir(source) or not os.path.isdir(dest):
            return {'error': "Not a dir: %s" % (source if not os.path.isdir(source) else dest,)}
        found = store.create(os.path.abspath(source), os.path.abspath(dest))
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
            copying.read(found.source)
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
        if found is not None:
            applying.apply(found)
        return {'ok': found is not None}

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
