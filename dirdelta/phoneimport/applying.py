"""Moving an import's copied files into the dirs chosen for them in its replica (apply()), on a thread of
its own: never over a file there (the same one, by its SHA-1, is left as it is and the copy removed; a
different one keeps its name, the moved one getting a free one), each moved file's SHA-1 kept in the
hash cache. A dry run (see dryrun.py) only says what it would do."""
import hashlib
import os
import threading

from dirdelta.hashes import hashcache
from dirdelta.phoneimport import store
from dirdelta.trees.localdiskdirtree import fs
from dirdelta.util import dryrun

# {import id: its Applying}, the ones running or done since the daemon started
_applyings = {}
_lock = threading.Lock()


class Applying(object):
    """Moving an import's files: is_done, and [(text, color)] lines saying what was done"""

    def __init__(self, found):
        self.import_ = found
        self.lines = []
        self.is_done = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        found = self.import_
        with found.lock:
            chosen = [(relpath, dict(info)) for relpath, info in found.files.items()
                      if info['state'] == store.COPIED and info.get('target') is not None]
        moved = there = 0
        for relpath, info in chosen:
            target_dir = os.path.join(found.dest, info['target'])
            new_path = os.path.join(target_dir, os.path.basename(relpath))
            if os.path.exists(new_path) and _sha1(new_path) == info['sha1']:
                there += 1
                if not dryrun.DRYRUN:
                    os.remove(found.local_path(relpath))
                    self._set_moved(relpath)
                continue
            new_path = _free(new_path)
            moved += 1
            self.lines.append(("%s %s → %s" % ("Would move" if dryrun.DRYRUN else "Moving", relpath,
                                               os.path.relpath(new_path, found.dest)), None))
            if dryrun.DRYRUN:
                continue
            try:
                os.makedirs(target_dir, exist_ok=True)
                fs.rename(found.local_path(relpath), new_path)
            except OSError as error:
                self.lines.append(("Couldn't move %s: %s" % (relpath, error.strerror), 'red'))
                continue
            if info.get('sha1'):
                hashcache.put(new_path, {'sha1': info['sha1']})
            self._set_moved(relpath)
        found.save()
        self.lines.append(("%s %d file(s)%s." % ("Would move" if dryrun.DRYRUN else "Moved", moved,
                                                ", %d there already" % (there,) if there else ""), 'green'))
        if dryrun.DRYRUN:
            self.lines.append((dryrun.NOTE, 'green'))
        self.is_done = True

    def _set_moved(self, relpath):
        with self.import_.lock:
            self.import_.files[relpath]['state'] = store.MOVED


def apply(found):
    """Start moving the import found's chosen files, unless it's being done; returns its Applying"""
    with _lock:
        applying = _applyings.get(found.id)
        if applying is not None and applying.thread.is_alive():
            return applying
        applying = _applyings[found.id] = Applying(found)
        applying.thread.start()
        return applying


def applying_of(import_id):
    with _lock:
        return _applyings.get(import_id)


def _free(path):
    """path, or if there's a file there, the first free 'name (2).ext' beside it"""
    base, extension = os.path.splitext(path)
    number = 2
    while os.path.exists(path):
        path = '%s (%d)%s' % (base, number, extension)
        number += 1
    return path


def _sha1(path):
    known = hashcache.get(path, 'sha1')
    if known:
        return known
    digest = hashlib.sha1()
    try:
        with open(path, 'rb') as found:
            for chunk in iter(lambda: found.read(1 << 20), b''):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
