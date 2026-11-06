"""Asking Claude about an inbox's dir as a whole"""
import collections
import os
import threading
import time

from dirdelta.claude import ai
from dirdelta.inbox.constants import DIR_FILES_DATED, DIR_FILES_DESCRIBED, NAMES_PER_DIR
from dirdelta.inbox.formatting import is_at_or_under, spread
from dirdelta.trees import entries
from dirdelta.trees import localscan


class ClaudeDirs(object):
    """Claude on dirs (InboxSort's)"""

    def ask_dir_in_background(self, dirpath, relpaths):
        """Have Claude say what the inbox's dir at dirpath (whose files are at relpaths) is, and what
        to do with it as a whole (ai.recommend_dir()), anew: a few of its files are described first,
        and all of them compared with the sorted tree's, so it knows how many are copies. On a thread
        of its own, while the user goes on; once the dir is asked about, Ctrl-I again does nothing."""
        with self._claude.lock:
            if dirpath in self._claude.dir_asking or not relpaths:
                return
            self._claude.dir_asking.add(dirpath)
            self._claude.dir_failed.pop(dirpath, None)
            self._claude.dir_recommendations.pop(dirpath, None)
            thread = threading.Thread(target=self._ask_about_dir, args=(dirpath, list(relpaths)), daemon=True)
            self._dir_threads.append(thread)
        thread.start()

    def _ask_about_dir(self, dirpath, relpaths):
        """ask_dir_in_background()'s thread"""
        try:
            described = spread(relpaths, DIR_FILES_DESCRIBED)
            undescribed = [relpath for relpath in described if relpath not in self._claude.descriptions]
            with self._claude.lock:
                self._claude.describing.update(undescribed)
            self._describe(undescribed)
            self._compare(relpaths)
            sizes = [self._listed(relpath)[0] or 0 for relpath in relpaths]
            types = collections.Counter(os.path.splitext(relpath)[1].lower() for relpath in relpaths)
            copies = len([relpath for relpath in relpaths if self._copies(relpath)])
            within = lambda relpath: relpath[len(dirpath) + 1:]
            dir_ = ai.Dir(dirpath, len(relpaths), sum(sizes), dict(types),
                          [within(relpath) for relpath in spread(relpaths, ai.DIR_NAMES_GIVEN)],
                          self._dates(spread(relpaths, DIR_FILES_DATED)),
                          {within(relpath): self._claude.descriptions[relpath] for relpath in described
                           if relpath in self._claude.descriptions}, copies)
            key = self._dir_key(dirpath, len(relpaths), sum(sizes))
            recommendation = ai.recommend_dir(dir_, key, self._root_dirs(), self.root_path, anew=True)
            with self._claude.lock:
                self._claude.dir_recommendations[dirpath] = (key, recommendation)
                self._claude.dir_copies[dirpath] = copies
        except Exception as error:
            self._claude.dir_failed[dirpath] = str(error)
        finally:
            with self._claude.lock:
                self._claude.dir_asking.discard(dirpath)

    def _dates(self, relpaths):
        """(the first, the last) of the dates ('YYYY-MM-DD') the inbox's files at relpaths were taken
        (photos), or else modified; None if none is known"""
        dates = []
        for relpath in relpaths:
            taken = self._inbox_tree.date_taken(relpath)
            if taken:
                dates.append(taken[:10])
                continue
            modified = self._inbox_tree.modified_time(relpath)
            if modified is not None:
                dates.append(time.strftime('%Y-%m-%d', time.localtime(modified)))
        return (min(dates), max(dates)) if dates else None

    def _root_dirs(self):
        """{dir relpath: the names of a few of its files (NAMES_PER_DIR)} of the sorted tree's dirs
        ('' its root), so Claude sees how they're named; not the inbox's (if it's in it)"""
        dirs = {'': []}
        if self.root_is_cloud:
            found = [(child.identifier, isinstance(child.data, entries.DirEntry))
                     for child in self._root_tree.nodes_under('') if child.identifier]
        else:
            found = [(relpath, kind == localscan.DIR) for relpath, (kind, _, _) in localscan.scan(self.root_path).entries.items()]
        found = [(relpath, is_dir) for relpath, is_dir in found
                 if self._inbox_in_root is None or not is_at_or_under(relpath, self._inbox_in_root)]
        for relpath, is_dir in sorted(found):
            if is_dir:
                dirs.setdefault(relpath, [])
        for relpath, is_dir in sorted(found):
            names = dirs.get(os.path.dirname(relpath))
            if not is_dir and names is not None and len(names) < NAMES_PER_DIR:
                names.append(os.path.basename(relpath))
        return dirs
