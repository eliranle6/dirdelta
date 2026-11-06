"""Waiting for Claude, and the files it's given (downloaded from Drive, if they must be)"""
import os
import time

from dirdelta.claude import ai
from dirdelta.inbox.constants import DESCRIBED_WAIT_INTERVAL, LOCK_GAP
from dirdelta.inbox.formatting import _dirs, _files
from dirdelta.ui import messages
from dirdelta.util import dryrun


class ClaudeFiles(object):
    """Claude's files (InboxSort's)"""

    def wait_for_claude(self):
        """Wait for what Claude is asked of files and dirs, without a screen (e.g. for a test)"""
        while True:
            worker = self._worker
            if worker is not None:
                worker.join()
                continue
            with self._state_lock:
                threads, self._dir_threads = self._dir_threads, []
            if not threads:
                return
            for thread in threads:
                thread.join()

    def _finish_describing(self):
        """Wait for what Claude is asked of files, if anything, on a progress screen (Ctrl-C stops
        waiting: what it said so far is kept)"""
        if not self._queued and not self._dir_asking:
            return
        title = ("Waiting for Claude to finish with %s (what it said so far is kept)" %
                 (', '.join(([_files(len(self._queued))] if self._queued else []) +
                            ([_dirs(len(self._dir_asking))] if self._dir_asking else [])),))
        failed_before = len(self._failed)
        with messages.progress_screen(title, dryrun.label(), wait=False):
            try:
                while self._queued or self._dir_asking:
                    messages.print_progress("%s left (%d being described, %d placed), %d failed%s" % (
                        _files(len(self._queued)), len(self._describing),
                        len(self._queued) - len(self._describing), len(self._failed) - failed_before,
                        "; %s being asked about" % (_dirs(len(self._dir_asking)),) if self._dir_asking else ""))
                    time.sleep(DESCRIBED_WAIT_INTERVAL)
            except KeyboardInterrupt:
                messages.note_stopped()
        if len(self._failed) > failed_before:
            messages.show("Claude couldn't finish with %s" % (_files(len(self._failed) - failed_before),),
                          [list(self._failed.values())[-1]], dryrun.label(), 'red')

    def _ai_files(self, relpaths):
        """ai.File of each of the inbox's files at relpaths: a Drive one downloaded first (one at a
        time; or found downloaded, see downloads.py), unless it's too big to be read, or a Google
        file, or it couldn't be: then Claude goes by its name. One that's not in the inbox anymore is
        left out. It prints nothing (a picker may have the screen). _drive_lock is held for each Drive
        file, not all of them, so the screen waits for one download at most."""
        if not self.inbox_is_cloud:
            return [ai.File(relpath, os.path.join(self.inbox_path, relpath), self._size(relpath))
                    for relpath in relpaths]
        files = []
        for relpath in relpaths:
            with self._drive_lock:
                if relpath in self._inbox_tree:
                    files.append(ai.File(relpath, self._downloaded_if_it_can_be(relpath), self._size(relpath)))
            # Else this thread takes the lock again before one waiting for it wakes up: measured, the
            # other waited for all of 58 files in a row, and for one with this
            time.sleep(LOCK_GAP)
        return files

    def _downloaded_if_it_can_be(self, relpath):
        """The local path of the inbox's Drive file at relpath for Claude, or None if it's too big to
        be read, a Google file, or it couldn't be downloaded"""
        if (self._size(relpath) or 0) > ai.MAX_READ_SIZE or self._inbox_tree.cant_fetch(relpath) is not None:
            return None
        try:
            return self._downloaded(relpath)
        except OSError:
            return None
