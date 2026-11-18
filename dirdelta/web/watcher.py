"""Watching for a phone being plugged in, or a known replica's dir appearing (its drive mounted), to say
so (Watcher): by looking every POLL_SECONDS, which needs nothing installed, and catches both. What's
there when it starts isn't said (it's not new); a path that comes and goes is said at most once every
QUIET_SECONDS, so a flaky USB link doesn't flood the user's mail. Each is said to whose it is (users.py):
a replica to the users who have it, a phone to the ones who imported from it (else the owner)."""
import os
import threading
import time

from dirdelta.known import replicas
from dirdelta.known import users
from dirdelta.phoneimport import sources
from dirdelta.phoneimport import store
from dirdelta.trees import paths
from dirdelta.ui.picker import updates

POLL_SECONDS = 5
QUIET_SECONDS = 600
PHONE, REPLICA = 'phone', 'replica'


def present():
    """{path: (kind, name, the users it's for)} of the phones' storages plugged in and the known local
    replicas there now"""
    found, phone_users = {}, {}
    for name in users.all_users():
        with users.acting_as(name):
            for found_import in store.all_imports():
                phone_users.setdefault(found_import.source, []).append(name)
            known_replicas = replicas.load()
            for pair in known_replicas.favorites + known_replicas.history + known_replicas.sorts:
                for path in pair:
                    if not paths.is_cloud_path(path) and os.path.isdir(path):
                        whose = found.setdefault(path, (REPLICA, path, []))[2]
                        if name not in whose:
                            whose.append(name)
    for name, path in sources.phones():
        found[path] = (PHONE, name, sorted(set(phone_users.get(path, []))) or [users.OWNER])
    return found


class Watcher(object):
    """Calls on_appear(kind, name, path, whose) on a thread of its own for each phone or replica that
    appears (whose: the users it's for)"""

    def __init__(self, on_appear, look=present):
        self._on_appear = on_appear
        self._look = look
        self._seen = None
        # {path: when it was last said}
        self._said = {}
        self._stop = threading.Event()

    def check(self, now=None):
        """Look once: say what appeared since the last look"""
        now = time.monotonic() if now is None else now
        found = self._look()
        if self._seen is not None:
            for path, (kind, name, whose) in found.items():
                if path not in self._seen and now - self._said.get(path, -QUIET_SECONDS) >= QUIET_SECONDS:
                    self._said[path] = now
                    self._on_appear(kind, name, path, whose)
        self._seen = set(found)

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:
                updates.log_error()
            self._stop.wait(POLL_SECONDS)
