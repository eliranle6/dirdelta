"""Asking Claude about the inbox's files in the background: describing them, and where they go"""
import threading

from dirdelta.claude import ai
from dirdelta.matching import elsewhere


class Claude(object):
    """Claude's queue of files (InboxSort's)"""

    # Claude

    def describe_in_background(self, relpaths):
        """Have Claude describe the files at relpaths (see ask_in_background())"""
        self.ask_in_background(relpaths, False)

    def ask_in_background(self, relpaths, place=True, anew=False):
        """Have Claude describe the files at relpaths that have no description, and with place, say
        where they go (what Enter's "Ask Claude where" did, and Ctrl-I does): their contents are
        compared with the sorted tree's files first, so Claude knows which are copies. On a thread
        of its own, a batch at a time, while the user goes on: each picker shows them as they come.
        With anew (Ctrl-I's), the ones asked about before are asked again, and compared again, since
        they (or the sorted tree) may have changed: what Claude said of them, here and in its cache,
        is dropped (but for the ones being asked about now)."""
        with self._state_lock:
            for relpath in relpaths:
                if anew and relpath not in self._queued:
                    self._forget(relpath)
                needs_description = relpath not in self._descriptions
                needs_place = place and relpath not in self._recommendations
                if not (needs_description or needs_place):
                    continue
                self._failed.pop(relpath, None)
                if needs_place:
                    self._placing.add(relpath)
                if relpath in self._queued:
                    continue
                self._queued.add(relpath)
                self._queue.append(relpath)
                if needs_description:
                    self._describing.add(relpath)
            if self._queue and self._worker is None:
                self._worker = threading.Thread(target=self._ask_queued, daemon=True)
                self._worker.start()

    def _forget(self, relpath):
        """Drop what's known of the inbox's file at relpath, to ask Claude about it anew (with the
        state lock)"""
        if (relpath in self._descriptions or relpath in self._recommendations or relpath in self._failed or
                relpath in self._checked):
            self._anew.add(relpath)
        self._descriptions.pop(relpath, None)
        self._recommendations.pop(relpath, None)
        self._failed.pop(relpath, None)
        self._checked.pop(relpath, None)

    def _ask_queued(self):
        """Ask Claude about the queued files, a batch at a time, until there are none (on the
        worker's thread: nothing is printed, as a picker may have the screen)"""
        while True:
            with self._state_lock:
                if not self._queue:
                    self._worker = None
                    return
                batch = [self._queue.popleft() for _ in range(min(ai.BATCH_SIZE, len(self._queue)))]
            try:
                self._describe(batch)
                self._place([relpath for relpath in batch if relpath in self._placing])
            finally:
                with self._state_lock:
                    self._describing.difference_update(batch)
                    self._placing.difference_update(batch)
                    self._queued.difference_update(batch)
                    self._anew.difference_update(batch)

    def _describe(self, batch):
        """Have Claude describe the files of batch that have no description (on the worker's thread)"""
        relpaths = [relpath for relpath in batch if relpath not in self._descriptions]
        try:
            if relpaths:
                files = self._ai_files(relpaths)
                found = ai.describe(files, self._cache_key, anew=self._anew & set(relpaths)) if files else {}
                self._descriptions.update(found)
                for relpath in (file.relpath for file in files):
                    if relpath not in found:
                        self._failed[relpath] = "Claude gave no description of it."
        except Exception as error:
            for relpath in relpaths:
                self._failed[relpath] = str(error)
        finally:
            with self._state_lock:
                self._describing.difference_update(batch)

    def _place(self, relpaths):
        """Have Claude say where the files at relpaths go, by their descriptions and which are copies
        of the sorted tree's files (their contents compared first), on the worker's thread"""
        relpaths = [relpath for relpath in relpaths if relpath not in self._recommendations]
        if not relpaths:
            return
        try:
            self._compare(relpaths)
            files = [ai.File(relpath, None, self._size(relpath)) for relpath in relpaths]
            found = ai.recommend(files, self._cache_key, self._root_dirs(), self.root_path, self._descriptions,
                                 {relpath: self._copies(relpath) for relpath in relpaths},
                                 anew=self._anew & set(relpaths))
            self._recommendations.update(found)
            for relpath in relpaths:
                if relpath not in found:
                    self._failed[relpath] = "Claude didn't say where it goes."
        except Exception as error:
            for relpath in relpaths:
                self._failed[relpath] = str(error)

    def _compare(self, relpaths):
        """Compare the contents of the inbox's files at relpaths with their candidates in the sorted
        tree, the ones not compared yet (once the sorted tree is listed)"""
        self._start_indexing()
        self._indexing.join()
        elsewhere.check_all(relpaths, self._inbox_tree, self._inbox_index, self._root_index, self._checked)
