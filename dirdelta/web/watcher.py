"""Watching for a phone being plugged in, or a known replica's dir appearing (its drive mounted), to say
so (Watcher): by looking every POLL_SECONDS, which needs nothing installed, and catches both. What's
there when it starts isn't said (it's not new); a path that comes and goes is said at most once every
QUIET_SECONDS, so a flaky USB link doesn't flood the user's mail. A replica is said only if it was known (and
not there) at the look before: one a sync has just used for the first time is new to the list, not newly there. Each is said to whose it is (users.py):
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


def known_replicas():
    """{path: the users who have it} of every known local replica, there now or not"""
    known = {}
    for name in users.all_users():
        with users.acting_as(name):
            found_replicas = replicas.load()
            for pair in found_replicas.favorites + found_replicas.history + found_replicas.sorts:
                for path in pair:
                    if not paths.is_cloud_path(path):
                        whose = known.setdefault(path, [])
                        if name not in whose:
                            whose.append(name)
    return known


def present():
    """{path: (kind, name, the users it's for)} of the phones' storages plugged in and the known local
    replicas there now"""
    found, phone_users = {}, {}
    for name in users.all_users():
        with users.acting_as(name):
            for found_import in store.all_imports():
                phone_users.setdefault(found_import.source, []).append(name)
    for path, whose in known_replicas().items():
        if os.path.isdir(path):
            found[path] = (REPLICA, path, whose)
    for name, path in sources.phones():
        found[path] = (PHONE, name, sorted(set(phone_users.get(path, []))) or [users.OWNER])
    return found


class Watcher(object):
    """Calls on_appear(kind, name, path, whose) on a thread of its own for each phone or replica that
    appears (whose: the users it's for)"""

    def __init__(self, on_appear, look=present, known=lambda: set(known_replicas())):
        self._on_appear = on_appear
        self._look = look
        self._known = known
        self._seen = None
        # The replicas known at the last look (one known only since then isn't said)
        self._known_before = set()
        # {path: when it was last said}
        self._said = {}
        self._stop = threading.Event()

    def check(self, now=None):
        """Look once: say what appeared since the last look"""
        now = time.monotonic() if now is None else now
        known = self._known()
        found = self._look()
        if self._seen is not None:
            for path, (kind, name, whose) in found.items():
                if kind == REPLICA and path not in self._known_before:
                    continue
                if path not in self._seen and now - self._said.get(path, -QUIET_SECONDS) >= QUIET_SECONDS:
                    self._said[path] = now
                    self._on_appear(kind, name, path, whose)
        self._seen = set(found)
        self._known_before = set(known)

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
