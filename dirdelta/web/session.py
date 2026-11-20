"""The web version's session (Session): dirdelta's flow (the start menu, a sync, a sort) run on a thread
of its own, as the user who started it, its pickers and messages shown in the browser (ui/frontend.py points the terminal's at it),
and what's shown now, each change numbered so the browsers (the laptop's, a phone's) wait for the next"""
import contextlib
import ctypes
import itertools
import threading

from dirdelta.known import users
from dirdelta.web import merging as web_merging
from dirdelta.web import messages as web_messages
from dirdelta.web import picker as web_picker

# How many lines printed between screens are kept (the first ones go)
MAX_LOG = 200
# How big a picture of a picker's preview is sent, at most (the page scales it to fit)
IMAGE_BOX = (480, 480)


class Session(object):
    image_box = IMAGE_BOX

    def __init__(self):
        self._condition = threading.Condition()
        # (From 1: a page's first ask, since 0, is answered at once, and the ones after it wait)
        self._version = 1
        self._ids = itertools.count(1)
        # The screens shown, the last on top (a picker may be shown on a progress screen)
        self._screens = []
        self.log = []
        self._flow = None
        # Who the flow running (or the last) is for: the user who started it; and its tab
        self.user = None
        self.tab = None
        # (What was asked to start it: e.g. {'kind': 'pair', 'a': ..., 'b': ...}, so a page can tell which)
        self.what = None

    # Changes, and waiting for them

    def bump(self):
        """A change: its version (and the browsers waiting are woken)"""
        with self._condition:
            self._version += 1
            self._condition.notify_all()
            return self._version

    @property
    def version(self):
        return self._version

    def wait(self, since, timeout):
        """Wait until something changes after the version since (or timeout seconds pass)"""
        with self._condition:
            self._condition.wait_for(lambda: self._version > since, timeout)
            return self._version

    def wait_for_screen(self, timeout):
        """While the flow runs between two screens (none shown), wait up to timeout seconds for the next"""
        with self._condition:
            self._condition.wait_for(lambda: self._screens or not self.is_running, timeout)

    def screen(self, screen_id=None):
        """The screen on top (or the one of screen_id, if it's still shown), or None"""
        with self._condition:
            if screen_id is None:
                return self._screens[-1] if self._screens else None
            return next((screen for screen in self._screens if screen.id == screen_id), None)

    @contextlib.contextmanager
    def _shown(self, screen):
        with self._condition:
            self._screens.append(screen)
        self.bump()
        try:
            yield screen
        finally:
            with self._condition:
                self._screens.remove(screen)
            self.bump()

    # The flow

    @property
    def is_running(self):
        return self._flow is not None and self._flow.is_alive()

    def start(self, flow, tab=None, what=None):
        """Run flow() on a thread of its own, unless one is running (tab: the page's tab it's under; what:
        what was asked to start it, kept to tell the pages).
        Returns whether it started."""
        if self.is_running:
            return False
        self.log = []
        self.tab = tab
        self.what = what
        self.user = users.current()
        self._flow = threading.Thread(target=self._run, args=(flow,), daemon=True)
        self._flow.start()
        self.bump()
        return True

    def _run(self, flow):
        # As the user who started it, and so are the threads it starts (the run's user then)
        users.set_default(self.user)
        try:
            with users.acting_as(self.user):
                flow()
            # (So a run that ended, e.g. gone back from, says so: the page shows nothing running then)
            self.print_line("The run ended.", 'grey')
        except KeyboardInterrupt:
            self.print_line("Stopped.")
        except SystemExit as error:
            self.print_line(str(error.code) if error.code not in (None, 0) else "The run ended.",
                            'red' if error.code not in (None, 0) else 'grey')
        except Exception as error:
            self.print_line("Something went wrong: %s" % (error,), 'red')
            raise
        finally:
            users.set_default(users.OWNER)
            self.bump()

    def stop(self):
        """Stop what the flow is doing, as Ctrl-C would: a KeyboardInterrupt in its thread"""
        if self.is_running:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(self._flow.ident),
                                                       ctypes.py_object(KeyboardInterrupt))

    def cancel(self):
        """End what's shown (as if quit), e.g. as the daemon stops"""
        for screen in list(self._screens):
            screen.cancel()

    # What dirdelta's picker calls (ui/picker/command.py)

    def run_picker(self, args, input_data):
        """treepicker's command with args (after its name) and input_data on its stdin (or None), done
        in the browser: (exit code, what it printed)"""
        spec = web_picker.parse(args)
        records = None
        if input_data is not None:
            records = [record.decode('utf-8', 'surrogateescape') for record in input_data.split(b'\0')[:-1]]
        with self._shown(web_picker.PickerScreen(next(self._ids), spec, records, self.bump)) as screen:
            return screen.run()

    # What dirdelta's messages call (ui/messages.py)

    def print_line(self, line, color=None):
        screen = self._messages_screen()
        if screen is not None:
            screen.print_line(line, color)
            return
        self.log.append((line, color))
        del self.log[:-MAX_LOG]
        self.bump()

    def print_progress(self, line):
        screen = self._messages_screen()
        if screen is not None:
            screen.print_progress(line)
        else:
            self.print_line(line)

    def _messages_screen(self):
        screen = self.screen()
        return screen if isinstance(screen, web_messages.MessagesScreen) else None

    @contextlib.contextmanager
    def progress_screen(self, title, label, is_stoppable, wait, on_stop):
        """As messages.progress_screen(): the lines printed inside on a screen of their own; on_stop()
        is called if the action was stopped (as its Ctrl-C would be)"""
        labels = [label] if label else []
        with self._shown(web_messages.MessagesScreen(next(self._ids), title, labels, is_stoppable, self.bump)) as screen:
            is_stopped = False
            try:
                yield
            except KeyboardInterrupt:
                is_stopped = True
                on_stop()
            if wait or is_stopped:
                screen.wait_continue(("Stopped" if is_stopped else "Done") if is_stoppable else "")

    def merge(self, title, names, lines_a, lines_b, label, suggest):
        """As merging.merge(): the merge window, until the page saves it (its lines) or goes back (None)"""
        with self._shown(web_merging.MergeScreen(next(self._ids), title, names, lines_a, lines_b, label, suggest,
                                                 self.bump)) as screen:
            return screen.run()

    def ask(self, title, lines, prompt, default, label):
        labels = [label] if label else []
        with self._shown(web_messages.MessagesScreen(next(self._ids), title, labels, False, self.bump)) as screen:
            for line in lines:
                screen.print_line(line)
            return screen.ask(prompt, default)
