"""The web version's tests' fixture (WebTest): a Session as dirdelta's frontend, and a call (a picker's, a
message's) run on a thread of its own, as the flow's is, with the test as the browser"""
import threading
import time
import unittest

import helpers  # noqa: F401 (the real caches and settings left alone)
from dirdelta.ui import frontend
from dirdelta.web.session import Session

TIMEOUT = 5


class WebTest(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        frontend.current = self.session
        self.addCleanup(setattr, frontend, 'current', None)
        self.addCleanup(self.session.cancel)

    def start(self, call):
        """Run call() as the flow would, until it shows a screen (returned); its result is result()'s"""
        self._result, self._error = None, None
        shown = self.session.screen()

        def run():
            try:
                self._result = call()
            except BaseException as error:
                self._error = error
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self.next_screen(shown)

    def next_screen(self, after=None):
        """The screen shown once it's not after (or None, once the call has returned)"""
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            screen = self.session.screen()
            if screen is not None and screen is not after:
                return screen
            if not self._thread.is_alive():
                return None
            time.sleep(0.01)
        self.fail("No screen was shown")

    def result(self):
        """What the call returned (or raises what it raised)"""
        self._thread.join(TIMEOUT)
        self.assertFalse(self._thread.is_alive(), "The call didn't return")
        if self._error is not None:
            raise self._error
        return self._result

    def wait_until(self, condition):
        deadline = time.monotonic() + TIMEOUT
        while not condition():
            if time.monotonic() > deadline:
                self.fail("It didn't happen")
            time.sleep(0.01)
