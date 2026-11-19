"""The imports kept (Import), one for each source and replica it goes into, each a folder of its own
under the user's IMPORTS_DIR (imports_dir_now(): each user's imports are their own, see users.py) with
its manifest (MANIFEST): where its files come from and go, and what was chosen
for them (a dir in the replica, or skipped) and done (moved), saved at each change. The files
themselves, their copies and hashes, are the source's pool's (pool.py), shared by its imports."""
import json
import os
import shutil
import threading
import time

from dirdelta.known import users

# The owner's (another user's: in a folder of theirs beside it; the sources' pools are all here)
IMPORTS_DIR = os.path.expanduser('~/.local/share/dirdelta/imports')
MANIFEST = 'import.json'
# Which of its files the replicas had when they were last checked (remember_where())
WHERE = 'where.json'
# How a file is there: by its contents, or by its name and size only
THERE_CONTENTS, THERE_NAME = 'contents', 'name'

# A file's states: on the source only, copied here (and hashed), moved into the replica, or left out
PENDING, COPIED, MOVED, SKIPPED = 'pending', 'copied', 'moved', 'skipped'

# {(the user's imports dir, id): its Import}, one object for each (as several requests change one)
_loaded = {}
_lock = threading.Lock()


class Import(object):
    """An import: its id (its folder's name), source (the dir its files come from: a phone's DCIM, or
    any), dest (the replica they're moved into) and dest_id (that replica's identity, replicanames':
    its disk's, so another disk mounted at its path is another replica), and choices: {relpath: {'target' (the dir in
    dest chosen for it, or None), 'state' (MOVED, SKIPPED, or None)}}"""

    def __init__(self, import_id, source, dest, dest_id=None, choices=None, created=None, imports_dir=None):
        self.id = import_id
        # (Its user's, kept: it's saved from other threads too)
        self.imports_dir = imports_dir or imports_dir_now()
        self.source = source
        self.dest = dest
        self.dest_id = dest_id
        self.choices = choices or {}
        self.created = created or time.time()
        self.lock = threading.RLock()
        # (where(): loaded once, then kept)
        self._where = None

    @property
    def folder(self):
        return os.path.join(self.imports_dir, self.id)

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

    def where(self):
        """{'files': {relpath: THERE_CONTENTS or THERE_NAME}, 'checked': 'YYYY-MM-DD HH:MM'}: which of the
        source's files a replica had, and how, when they were last checked (kept: the phone may be
        unplugged since); None if they never were"""
        with self.lock:
            if self._where is None:
                try:
                    with open(os.path.join(self.folder, WHERE)) as kept:
                        content = json.load(kept)
                    self._where = {'files': dict(content['files']), 'checked': content.get('checked')}
                except (OSError, ValueError, KeyError, TypeError):
                    self._where = {}
            return self._where or None

    def remember_where(self, files, checked):
        """Keep files ({relpath: THERE_CONTENTS or THERE_NAME}) as what the replicas had, checked when
        checked says ('YYYY-MM-DD HH:MM'), if that's news"""
        found = {'files': files, 'checked': checked}
        with self.lock:
            if self.where() == found:
                return
            self._where = found
            os.makedirs(self.folder, exist_ok=True)
            temp_path = os.path.join(self.folder, WHERE + '.tmp')
            with open(temp_path, 'w') as kept:
                json.dump(found, kept)
            os.replace(temp_path, os.path.join(self.folder, WHERE))

    def save(self):
        with self.lock:
            os.makedirs(self.folder, exist_ok=True)
            temp_path = os.path.join(self.folder, MANIFEST + '.tmp')
            with open(temp_path, 'w') as manifest:
                json.dump({'source': self.source, 'dest': self.dest, 'destId': self.dest_id, 'created': self.created,
                           'choices': self.choices}, manifest)
            os.replace(temp_path, os.path.join(self.folder, MANIFEST))

    def end(self):
        """Remove the import, and its source's pool (copies, thumbnails, hashes) if no other import
        has that source (any user's)"""
        source_pool = self.pool
        with _lock:
            _loaded.pop((self.imports_dir, self.id), None)
        shutil.rmtree(self.folder, ignore_errors=True)
        if not any(other.source == self.source for other in everyones_imports()):
            source_pool.remove()


def find(source, dest, dest_id):
    """The import of source into the replica dest_id (at dest), or None (one made before imports kept
    their replica's identity is taken as that one's, and keeps it from now on)"""
    for found in all_imports():
        if (found.source, found.dest) == (source, dest) and found.dest_id in (None, dest_id):
            if found.dest_id is None:
                found.dest_id = dest_id
                found.save()
            return found
    return None


def imports_dir_now():
    """The current user's imports' dir"""
    return users.own(IMPORTS_DIR)


def create(source, dest, dest_id):
    """The import of source into the replica dest_id (at dest): the one there is, or a new one, saved
    (its id: when it started, and a number if that's taken)"""
    found = find(source, dest, dest_id)
    if found is not None:
        return found
    base = time.strftime('%Y-%m-%d-%H%M%S')
    import_id, number = base, 1
    folder = imports_dir_now()
    while os.path.exists(os.path.join(folder, import_id)):
        number += 1
        import_id = '%s-%d' % (base, number)
    found = Import(import_id, source, dest, dest_id, imports_dir=folder)
    found.save()
    with _lock:
        _loaded[(folder, import_id)] = found
    return found


def load(import_id):
    """The import of import_id, or None if there's none"""
    if not import_id or '/' in import_id or import_id.startswith('.'):
        return None
    folder = imports_dir_now()
    with _lock:
        found = _loaded.get((folder, import_id))
    if found is not None:
        return found
    try:
        with open(os.path.join(folder, import_id, MANIFEST)) as manifest:
            content = json.load(manifest)
    except (OSError, ValueError):
        return None
    found = Import(import_id, content['source'], content['dest'], content.get('destId'), content.get('choices', {}),
                   content.get('created'), folder)
    with _lock:
        return _loaded.setdefault((folder, import_id), found)


def all_imports():
    """The imports kept, the latest first"""
    try:
        names = os.listdir(imports_dir_now())
    except OSError:
        return []
    found = [load(name) for name in sorted(names, reverse=True)]
    return [one for one in found if one is not None]


def everyones_imports():
    """Every user's imports"""
    found = []
    for name in users.all_users():
        with users.acting_as(name):
            found += all_imports()
    return found
