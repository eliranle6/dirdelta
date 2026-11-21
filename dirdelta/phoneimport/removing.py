"""Removing an import's files from its source (remove()): the phone's, a folder's, a Drive inbox's (to Drive's trash),
once the replica it goes into has them (the page offers it for those alone, and the route checks it), on a thread of
its own, as moving does (applying.py): each removed one dropped from the source's pool (its copy here too), so the
import doesn't list it any more. A dry run (see dryrun.py) only says what it would do."""
import os
import subprocess
import threading

from dirdelta.util import dryrun

# {import id: its Removing}, the ones running or done since the daemon started
_removings = {}
_lock = threading.Lock()


class Removing(object):
    """Removing an import's files from its source: is_done, and [(text, color)] lines saying what was done"""

    def __init__(self, found, relpaths):
        self.import_, self.relpaths = found, list(relpaths)
        self.lines = []
        self.is_done = False
        self.nr_removed = 0
        self.nr_total, self.nr_done = len(self.relpaths), 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        found = self.import_
        try:
            if dryrun.DRYRUN:
                self.nr_removed = self.nr_done = len(self.relpaths)
            elif found.pool.is_drive:
                self._from_drive()
            else:
                for relpath in self.relpaths:
                    self.nr_done += 1
                    if self._remove_local(os.path.join(found.source, relpath)):
                        self._forget(relpath)
        finally:
            found.pool.save()
            where = "the phone" if found.source.startswith('/run/') else "Drive" if found.pool.is_drive else "the folder"
            self.lines.append(("%s %d file(s) from %s." % ("Would remove" if dryrun.DRYRUN else "Removed", self.nr_removed, where), 'green'))
            if dryrun.DRYRUN:
                self.lines.append((dryrun.note(), 'green'))
            self.is_done = True

    def _remove_local(self, path):
        """Remove the file at path (a phone's, through gvfs: gio if the mount won't unlink it); whether it's gone"""
        try:
            os.remove(path)
        except FileNotFoundError:
            return True
        except OSError as error:
            done = subprocess.run(['gio', 'remove', path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            if done.returncode != 0:
                self.lines.append(("Couldn't remove %s: %s" % (path, error.strerror or error), 'red'))
                return False
        self.nr_removed += 1
        return True

    def _from_drive(self):
        """The files to Drive's trash, through the folder's tree (as a sort removes from a Drive inbox)"""
        from dirdelta.drive import clouddirtree
        found = self.import_
        tree = clouddirtree.factory(found.source)
        file_entries = [tree.get_node(relpath).data for relpath in self.relpaths if relpath in tree]
        tree.remove_files(file_entries)
        for relpath in self.relpaths:
            if relpath not in tree:
                self.nr_removed += 1
                self._forget(relpath)

    def _forget(self, relpath):
        """The file is gone from the source: from its pool too, its copy and thumbnail with it"""
        source_pool = self.import_.pool
        with source_pool.lock:
            source_pool.files.pop(relpath, None)
        for path in (source_pool.local_path(relpath), source_pool.thumb_path(relpath)):
            try:
                os.remove(path)
            except OSError:
                pass


def remove(found, relpaths):
    """Start removing the import found's files at relpaths from its source, unless one's going on; returns its Removing"""
    with _lock:
        removing = _removings.get(found.id)
        if removing is not None and removing.thread.is_alive():
            return removing
        removing = _removings[found.id] = Removing(found, relpaths)
        removing.thread.start()
        return removing


def removing_of(import_id):
    with _lock:
        return _removings.get(import_id)
