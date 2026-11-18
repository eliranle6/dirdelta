"""Moving an import's files into the dirs chosen for them in its replica (apply()), on a thread of its
own: one not copied yet copied from the source first (a Drive file downloaded), never over a file there
(the same one, by its SHA-1, is left as it is and the copy removed; a different one keeps its name, the
moved one getting a free one), each moved file's SHA-1 kept in the hash cache; a Drive file then moved to
Drive's trash, as a sort moves it out of its inbox. From Drive into Drive, a file is moved in Drive
(keeping its id). A dry run (see dryrun.py) only says what it would do."""
import hashlib
import os
import threading

from dirdelta.hashes import hashcache
from dirdelta.phoneimport import copying, store
from dirdelta.trees import entries
from dirdelta.trees import paths
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
        self.nr_moved = self.nr_there = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        found = self.import_
        chosen = [(relpath, info) for relpath, info in found.files().items()
                  if info['state'] in (store.PENDING, store.COPIED) and info.get('target') is not None]
        try:
            if found.pool.is_drive and paths.is_cloud_path(found.dest):
                self._within_drive(chosen)
            else:
                self._into_local(chosen)
        finally:
            found.save()
            found.pool.save()
            self.lines.append(("%s %d file(s)%s." % ("Would move" if dryrun.DRYRUN else "Moved", self.nr_moved,
                                                    ", %d there already" % (self.nr_there,) if self.nr_there else ""), 'green'))
            if dryrun.DRYRUN:
                self.lines.append((dryrun.NOTE, 'green'))
            self.is_done = True

    def _into_local(self, chosen):
        found, source_pool = self.import_, self.import_.pool
        for relpath, info in chosen:
            if info['state'] == store.PENDING and not dryrun.DRYRUN:
                try:
                    info['sha1'] = copying.copy_one(source_pool, relpath)
                except OSError as error:
                    self.lines.append(("Couldn't copy %s from %s: %s" % (relpath, "Drive" if source_pool.is_drive else "the phone",
                                                                      error.strerror or error), 'red'))
                    continue
            target_dir = os.path.join(found.dest, info['target'])
            new_path = os.path.join(target_dir, os.path.basename(relpath))
            if os.path.exists(new_path) and _sha1(new_path) == info['sha1']:
                self.nr_there += 1
                if not dryrun.DRYRUN:
                    os.remove(source_pool.local_path(relpath))
                    self._done(relpath)
                continue
            new_path = _free(new_path)
            self.nr_moved += 1
            self.lines.append(("%s %s → %s" % ("Would move" if dryrun.DRYRUN else "Moving", relpath,
                                               os.path.relpath(new_path, found.dest)), None))
            if dryrun.DRYRUN:
                continue
            try:
                os.makedirs(target_dir, exist_ok=True)
                fs.rename(source_pool.local_path(relpath), new_path)
            except OSError as error:
                self.lines.append(("Couldn't move %s: %s" % (relpath, error.strerror), 'red'))
                continue
            if info.get('sha1'):
                hashcache.put(new_path, {'sha1': info['sha1']})
            self._done(relpath)

    def _within_drive(self, chosen):
        from dirdelta.drive.clouddirtree import tree as clouddirtree
        found, source_pool = self.import_, self.import_.pool
        source_tree, dest_tree = source_pool.tree(), clouddirtree.factory(found.dest)
        for relpath, info in chosen:
            new_relpath = '/'.join(part for part in (info['target'], os.path.basename(relpath)) if part)
            if dest_tree.has_file(new_relpath) and dest_tree.known_hash(new_relpath, 'sha1') == info['sha1']:
                self.nr_there += 1
                if not dryrun.DRYRUN:
                    self._done(relpath, source_tree)
                continue
            new_relpath = _free(new_relpath, dest_tree.has_file)
            self.nr_moved += 1
            self.lines.append(("%s %s → %s" % ("Would move" if dryrun.DRYRUN else "Moving", relpath, new_relpath), None))
            if not dryrun.DRYRUN and source_tree.move_files([(relpath, new_relpath)], to=dest_tree):
                found.set_moved(relpath)
                source_pool.gone(relpath)

    def _done(self, relpath, drive_tree=None):
        """The file at relpath is in the replica now: its copy's gone, and a Drive one's moved to the trash"""
        found, source_pool = self.import_, self.import_.pool
        source_pool.gone(relpath)
        found.set_moved(relpath)
        if source_pool.is_drive:
            tree = drive_tree or source_pool.tree()
            node = tree.get_node(relpath)
            tree.remove_files([node.data if node is not None else
                               entries.FileEntry(os.path.basename(relpath), relpath, os.path.join(tree.fullpath(), relpath))])


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


def _free(path, exists=os.path.exists):
    """path, or if there's a file there (by exists()), the first free 'name (2).ext' beside it"""
    base, extension = os.path.splitext(path)
    number = 2
    while exists(path):
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
