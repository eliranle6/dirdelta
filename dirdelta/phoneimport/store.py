"""The imports kept (Import), one for each source and replica it goes into, each a folder of its own
under IMPORTS_DIR with its manifest (MANIFEST): where its files come from and go, and what was chosen
for them (a dir in the replica, or skipped) and done (moved), saved at each change. The files
themselves, their copies and hashes, are the source's pool's (pool.py), shared by its imports."""
import json
import os
import shutil
import threading
import time

IMPORTS_DIR = os.path.expanduser('~/.local/share/dirdelta/imports')
MANIFEST = 'import.json'

# A file's states: on the source only, copied here (and hashed), moved into the replica, or left out
PENDING, COPIED, MOVED, SKIPPED = 'pending', 'copied', 'moved', 'skipped'

# {(IMPORTS_DIR, id): its Import}, one object for each (as several requests change one)
_loaded = {}
_lock = threading.Lock()


class Import(object):
    """An import: its id (its folder's name), source (the dir its files come from: a phone's DCIM, or
    any), dest (the local replica they're moved into), and choices: {relpath: {'target' (the dir in
    dest chosen for it, or None), 'state' (MOVED, SKIPPED, or None)}}"""

    def __init__(self, import_id, source, dest, choices=None, created=None):
        self.id = import_id
        self.source = source
        self.dest = dest
        self.choices = choices or {}
        self.created = created or time.time()
        self.lock = threading.RLock()

    @property
    def folder(self):
        return os.path.join(IMPORTS_DIR, self.id)

    @property
    def pool(self):
        from dirdelta.phoneimport import pool
        return pool.of(self.source)

    def files(self):
        """{relpath: {'size', 'mtime', 'sha1', 'state', 'target'}}: the source's files, as listed, with
        what was chosen and done here"""
        source_pool = self.pool
        with source_pool.lock, self.lock:
            found = {}
            for relpath, info in source_pool.files.items():
                choice = self.choices.get(relpath, {})
                state = choice.get('state') or (COPIED if info['copied'] else PENDING)
                found[relpath] = {'size': info['size'], 'mtime': info['mtime'], 'sha1': info['sha1'],
                                  'state': state, 'target': choice.get('target')}
            return found

    def choose(self, relpaths, target=None, skip=False):
        """Choose the dir target for the files at relpaths (or skip them; None: neither), but the
        moved ones"""
        with self.lock:
            for relpath in relpaths:
                choice = self.choices.setdefault(relpath, {})
                if choice.get('state') == MOVED:
                    continue
                choice.update(state=SKIPPED if skip else None, target=None if skip else target)
            self.save()

    def set_moved(self, relpath):
        with self.lock:
            self.choices.setdefault(relpath, {})['state'] = MOVED

    def counts(self):
        """{state: how many files are in it}"""
        found = {PENDING: 0, COPIED: 0, MOVED: 0, SKIPPED: 0}
        for info in self.files().values():
            found[info['state']] += 1
        return found

    def save(self):
        with self.lock:
            os.makedirs(self.folder, exist_ok=True)
            temp_path = os.path.join(self.folder, MANIFEST + '.tmp')
            with open(temp_path, 'w') as manifest:
                json.dump({'source': self.source, 'dest': self.dest, 'created': self.created,
                           'choices': self.choices}, manifest)
            os.replace(temp_path, os.path.join(self.folder, MANIFEST))

    def end(self):
        """Remove the import, and its source's pool (copies, thumbnails, hashes) if no other import
        has that source"""
        source_pool = self.pool
        with _lock:
            _loaded.pop((IMPORTS_DIR, self.id), None)
        shutil.rmtree(self.folder, ignore_errors=True)
        if not any(other.source == self.source for other in all_imports()):
            source_pool.remove()


def find(source, dest):
    """The import of source into dest, or None"""
    return next((found for found in all_imports() if (found.source, found.dest) == (source, dest)), None)


def create(source, dest):
    """The import of source into dest: the one there is, or a new one, saved (its id: when it
    started, and a number if that's taken)"""
    found = find(source, dest)
    if found is not None:
        return found
    base = time.strftime('%Y-%m-%d-%H%M%S')
    import_id, number = base, 1
    while os.path.exists(os.path.join(IMPORTS_DIR, import_id)):
        number += 1
        import_id = '%s-%d' % (base, number)
    found = Import(import_id, source, dest)
    found.save()
    with _lock:
        _loaded[(IMPORTS_DIR, import_id)] = found
    return found


def load(import_id):
    """The import of import_id, or None if there's none"""
    if not import_id or '/' in import_id or import_id.startswith('.'):
        return None
    with _lock:
        found = _loaded.get((IMPORTS_DIR, import_id))
    if found is not None:
        return found
    try:
        with open(os.path.join(IMPORTS_DIR, import_id, MANIFEST)) as manifest:
            content = json.load(manifest)
    except (OSError, ValueError):
        return None
    found = Import(import_id, content['source'], content['dest'], content.get('choices', {}), content.get('created'))
    with _lock:
        return _loaded.setdefault((IMPORTS_DIR, import_id), found)


def all_imports():
    """The imports kept, the latest first"""
    try:
        names = os.listdir(IMPORTS_DIR)
    except OSError:
        return []
    found = [load(name) for name in sorted(names, reverse=True)]
    return [one for one in found if one is not None]
