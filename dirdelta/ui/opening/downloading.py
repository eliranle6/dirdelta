"""An opener's queue of files, downloaded and opened one after another in the background"""
import subprocess
import time

from dirdelta.ui.opening.names import COLOR, SHOWN_FOR, _FAILED, _OPENED, _WAITING, _files


class Downloading(object):
    """The queue (Opener's)"""

    def _enqueue(self, relpaths, files):
        """Queue the files; returns whether a worker is to be started (none is running)"""
        to_download = dict(self.to_download(relpaths, files))
        with self._lock:
            if not self._is_running:
                self._total = self._done = self._nr_total = self._nr_done = 0
                self._opened, self._failed = [], []
                self._states = {}
            for relpath in relpaths:
                self._queue.append((relpath, relpath in files))
                if relpath in to_download:
                    self._states[relpath] = [_WAITING, 0]
                    self._tagged.add(relpath)
                    self._total += to_download[relpath] or 0
                    self._nr_total += 1
            is_starting = not self._is_running
            self._is_running = True
        return is_starting

    def _work(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._is_running = False
                    self._note = (self._summary(), COLOR, time.monotonic() + SHOWN_FOR)
                    return
                relpath, is_file = self._queue.pop(0)
            name = self._name(relpath)
            try:
                path = self._local_path(relpath, is_file)
                # Its own session, so it outlives the picker (and dirdelta), and says nothing on
                # its screen
                subprocess.Popen(['xdg-open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                self._end(relpath, _OPENED)
                self._opened.append(name)
            except OSError as error:
                self._end(relpath, _FAILED)
                self._failed.append((name, error))

    def _end(self, relpath, state):
        with self._lock:
            if relpath in self._states and self._states[relpath][0] != state:
                self._states[relpath][0] = state
                self._done += self._size(relpath)
                self._nr_done += 1

    def _summary(self):
        """What the status bar says once they're all done"""
        opened, failed = self._opened, self._failed
        if not failed:
            return "Opened %s" % (opened[0] if len(opened) == 1 else _files(len(opened)),)
        name, error = failed[-1]
        text = ("Couldn't open %s: %s" % (name, error) if len(failed) == 1 else
                "Couldn't open %s (%s: %s)" % (_files(len(failed)), name, error))
        if opened:
            text += "; opened %s" % (opened[0] if len(opened) == 1 else _files(len(opened)),)
        return text
