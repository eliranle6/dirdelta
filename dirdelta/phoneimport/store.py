"""The imports kept (Import): each a folder of its own under IMPORTS_DIR, with the files copied from
its source (files/, at their paths there) and its manifest (MANIFEST): where they came from, where they
go (a local replica), and each file's state, saved at each change, so an import goes on where it was
after the phone is unplugged, the daemon restarts or the computer does"""
import json
import os
import threading
import time

IMPORTS_DIR = os.path.expanduser('~/.local/share/dirdelta/imports')
MANIFEST = 'import.json'
FILES_DIR = 'files'

# A file's states: to copy, copied (here, with its SHA-1), moved into the replica, or left out
PENDING, COPIED, MOVED, SKIPPED = 'pending', 'copied', 'moved', 'skipped'


class Import(object):
    """An import: its id (its folder's name), source (the dir its files are copied from: a phone's, or
    any), dest (the local replica they're moved into), and files: {relpath: {'size', 'mtime', 'state',
    'sha1', 'target' (the dir in dest chosen for it, or None)}}"""

    def __init__(self, import_id, source, dest, files=None, created=None):
        self.id = import_id
        self.source = source
        self.dest = dest
        self.files = files or {}
        self.created = created or time.time()
        self.lock = threading.RLock()

    @property
    def folder(self):
        return os.path.join(IMPORTS_DIR, self.id)

    def local_path(self, relpath):
        """Where the file at relpath is copied to"""
        return os.path.join(self.folder, FILES_DIR, relpath)

    def add(self, listed):
        """Add the files listed ({relpath: (size, mtime)}) that it hasn't got, to copy (a file listed
        again, changed, is copied again unless it's been moved)"""
        with self.lock:
            for relpath, (size, mtime) in listed.items():
                found = self.files.get(relpath)
                if found is None or (found['state'] != MOVED and (found['size'], found['mtime']) != (size, mtime)):
                    self.files[relpath] = {'size': size, 'mtime': mtime, 'state': PENDING, 'sha1': None,
                                           'target': found and found.get('target')}
            self.save()

    def counts(self):
        """{state: how many files are in it}"""
        with self.lock:
            found = {PENDING: 0, COPIED: 0, MOVED: 0, SKIPPED: 0}
            for info in self.files.values():
                found[info['state']] += 1
            return found

    def save(self):
        with self.lock:
            os.makedirs(self.folder, exist_ok=True)
            temp_path = os.path.join(self.folder, MANIFEST + '.tmp')
            with open(temp_path, 'w') as manifest:
                json.dump({'source': self.source, 'dest': self.dest, 'created': self.created, 'files': self.files},
                          manifest)
            os.replace(temp_path, os.path.join(self.folder, MANIFEST))


def create(source, dest):
    """A new import from source into dest, saved (its id: when it started, and a number if that's taken)"""
    base = time.strftime('%Y-%m-%d-%H%M%S')
    import_id, number = base, 1
    while os.path.exists(os.path.join(IMPORTS_DIR, import_id)):
        number += 1
        import_id = '%s-%d' % (base, number)
    found = Import(import_id, source, dest)
    found.save()
    return found


def load(import_id):
    """The import of import_id, or None if there's none"""
    if not import_id or '/' in import_id or import_id.startswith('.'):
        return None
    try:
        with open(os.path.join(IMPORTS_DIR, import_id, MANIFEST)) as manifest:
            content = json.load(manifest)
    except (OSError, ValueError):
        return None
    return Import(import_id, content['source'], content['dest'], content.get('files', {}), content.get('created'))


def all_imports():
    """The imports kept, the latest first"""
    try:
        names = os.listdir(IMPORTS_DIR)
    except OSError:
        return []
    found = [load(name) for name in sorted(names, reverse=True)]
    return [one for one in found if one is not None]
