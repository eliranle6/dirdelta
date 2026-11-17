"""The import page's API (routes()): the imports and the phones plugged in, starting one, an import's
files by day (each with where the replicas have it already, and suggestions), their thumbnails, the
dirs chosen for them, copying again and moving them in (see phoneimport/)"""
import datetime
import os
import threading

from dirdelta.known import replicas
from dirdelta.phoneimport import applying, copying, known, sources, store, suggest, thumbs
from dirdelta.trees import paths
from dirdelta.util import dryrun
from dirdelta.web.server import Reply


class _KnownCache(object):
    """Each destination's Known (it and its synced replicas), indexed on a thread once it's asked for"""

    def __init__(self):
        self._known, self._lock = {}, threading.Lock()

    def get(self, dest):
        with self._lock:
            found = self._known.get(dest)
            if found is None:
                found = self._known[dest] = known.Known([dest] + synced_with(dest))
                found.suggester = None
                threading.Thread(target=self._index, args=(found, dest), daemon=True).start()
            return found

    @staticmethod
    def _index(found, dest):
        found.index()
        found.suggester = suggest.Suggester(found.media_relpaths(dest))


def synced_with(path):
    """The replicas the replica at path was synced with (the favorites', the history's)"""
    path = paths.normalized(path)
    known_replicas = replicas.load()
    return list(dict.fromkeys(other for pair in known_replicas.favorites + known_replicas.history if path in pair
                              for other in pair if other != path))


def destinations():
    """The local replicas an import may go into (the sorted trees first), and the default one"""
    known_replicas = replicas.load()
    candidates = [root for _, root in known_replicas.sorts] + [path for pair in known_replicas.favorites +
                                                               known_replicas.history for path in pair]
    local = [path for path in dict.fromkeys(candidates) if not paths.is_cloud_path(path) and os.path.isdir(path)]
    return local, local[0] if local else None


def routes():
    cache = _KnownCache()

    def listing(query, body):
        dests, default = destinations()
        return {'imports': [_summary(found) for found in store.all_imports()],
                'phones': [{'name': name, 'path': path} for name, path in sources.phones()],
                'dests': dests, 'defaultDest': default, 'label': list(dryrun.label())}

    def new(query, body):
        source, dest = body.get('source', ''), body.get('dest', '')
        if not os.path.isdir(source) or not os.path.isdir(dest):
            return {'error': "Not a dir: %s" % (source if not os.path.isdir(source) else dest,)}
        found = store.create(os.path.abspath(source), os.path.abspath(dest))
        copying.copy(found)
        cache.get(found.dest)
        return {'id': found.id}

    def state(query, body):
        found = store.load(query.get('id'))
        if found is None:
            return {'error': 'No such import'}
        live = (copying.copying_of(found.id) or applying.applying_of(found.id))
        found = live.import_ if live is not None else found
        return _state(found, cache.get(found.dest))

    def thumb(query, body):
        found = _live(query.get('id'))
        data = thumbs.jpeg(found, query.get('rel', '')) if found is not None and _is_inside(query.get('rel', '')) else None
        return Reply(data, 'image/jpeg', is_kept=True) if data else Reply(b'', 'text/plain', 404)

    def assign(query, body):
        found = _live(body.get('id'))
        if found is None:
            return {'ok': False}
        with found.lock:
            for relpath in body.get('rels', []):
                info = found.files.get(relpath)
                if info is None or info['state'] == store.MOVED:
                    continue
                if body.get('skip'):
                    info['state'], info['target'] = store.SKIPPED, None
                else:
                    target = body.get('target')
                    info['target'] = target.strip('/') if target and _is_inside(target) else None
                    if info['state'] == store.SKIPPED:
                        info['state'] = store.COPIED if info.get('sha1') else store.PENDING
            found.save()
        return {'ok': True}

    def copy_again(query, body):
        found = _live(body.get('id'))
        if found is not None:
            copying.copy(found)
        return {'ok': found is not None}

    def apply(query, body):
        found = _live(body.get('id'))
        if found is not None:
            applying.apply(found)
        return {'ok': found is not None}

    return {('GET', '/api/imports'): listing, ('POST', '/api/imports/new'): new, ('GET', '/api/import'): state,
            ('GET', '/api/import/thumb'): thumb, ('POST', '/api/import/assign'): assign,
            ('POST', '/api/import/copy'): copy_again, ('POST', '/api/import/apply'): apply}


def _live(import_id):
    """The import being copied or moved (whose files are changing), else the one kept"""
    live = copying.copying_of(import_id) or applying.applying_of(import_id)
    return live.import_ if live is not None else store.load(import_id)


def _is_inside(relpath):
    return not os.path.isabs(relpath) and '..' not in relpath.split('/')


def _summary(found):
    return {'id': found.id, 'source': found.source, 'dest': found.dest, 'created': found.created,
            'counts': found.counts()}


def _state(found, known_now):
    is_indexed = getattr(known_now, 'suggester', None) is not None
    days = {}
    with found.lock:
        files = sorted(found.files.items(), key=lambda item: (suggest.date_of(item[0], item[1]['mtime']) or 0, item[0]))
    for relpath, info in files:
        day = suggest.date_of(relpath, info['mtime'])
        have = [{'replica': replica, 'relpath': where, 'how': how} for replica, where, how in
                known_now.found(relpath, info['size'], info.get('sha1'))] if is_indexed else None
        days.setdefault(str(day), []).append(dict(info, rel=relpath, have=have))
    copying_now, applying_now = copying.copying_of(found.id), applying.applying_of(found.id)
    return dict(_summary(found), label=list(dryrun.label()), checked=known_now.replica_paths, indexed=is_indexed,
                errors=known_now.errors,
                folders=known_now.dirs.get(found.dest, []) if is_indexed else [],
                days=[{'day': day, 'files': day_files,
                       'suggested': known_now.suggester.suggest(_date(day)) if is_indexed else []}
                      for day, day_files in days.items()],
                copying={'phase': copying_now.phase, 'message': copying_now.message} if copying_now else None,
                applying={'done': applying_now.is_done, 'lines': applying_now.lines} if applying_now else None)


def _date(text):
    """The date of a day's key (str(a date)), or None for the files without one"""
    return None if text == 'None' else datetime.date.fromisoformat(text)
