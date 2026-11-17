"""dirdelta's messages (ui/messages.py) in the browser: a screen of lines under a title (MessagesScreen),
shown while an action runs (Stop stops it, as Ctrl-C does) and then until Continue is pressed, or
asking for a line of text"""
import threading

# How many lines a screen keeps (the first ones go)
MAX_LINES = 2000


class MessagesScreen(object):
    kind = 'messages'

    def __init__(self, screen_id, title, label, is_stoppable, bump):
        self.id = screen_id
        self.title = title
        self.label = label
        self.is_stoppable = is_stoppable
        self._bump = bump
        # [(text, color)], the last one replaced while it's a progress line
        self.lines = []
        self._is_progress = False
        self.status = 'Working...' if is_stoppable else ''
        self.waiting = False
        self.asking = None
        self._answer = None
        self._answered = threading.Event()
        self.version = bump()

    def print_line(self, line, color=None):
        # (A progress line stays, as on the terminal: only the next progress line replaces it)
        self._is_progress = False
        self._add(line, color)

    def print_progress(self, line):
        if self._is_progress:
            self.lines.pop()
        self._add(line, None)
        self._is_progress = True

    def _add(self, line, color):
        self.lines.append((line, color))
        del self.lines[:-MAX_LINES]
        self.version = self._bump()

    def wait_continue(self, status):
        """Wait until the browser says to go on, saying status (done, stopped)"""
        self.status = status
        self.waiting = True
        self.version = self._bump()
        self._answered.wait()

    def ask(self, prompt, default):
        """Wait for the browser's answer to prompt (a line, starting as default), or None for none"""
        self.asking = {'prompt': prompt, 'default': default}
        self.version = self._bump()
        self._answered.wait()
        return self._answer

    def answer(self, text=None):
        """The browser's Continue (or its answer)"""
        self._answer = text
        self.waiting = False
        self.asking = None
        self._answered.set()
        self.version = self._bump()

    def cancel(self):
        self.answer(None)

    def meta(self):
        return {'kind': self.kind, 'id': self.id, 'title': self.title,
                'labels': [list(label) for label in self.label], 'stoppable': self.is_stoppable}

    def state(self, since):
        return {'lines': [list(line) for line in self.lines], 'status': self.status, 'waiting': self.waiting,
                'asking': self.asking}
