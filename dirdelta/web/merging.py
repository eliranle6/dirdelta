"""A merge of two versions of a text file in the browser (ui/merging.py's merge()): the versions' blocks
sent to the page, which makes the merged text (each differing block's version chosen, or both, then
edited) and saves it or goes back (MergeScreen); and the AI's merge, asked for on a thread of its own,
its answer sent as it comes"""
import threading

from dirdelta.ui import merging


class MergeScreen(object):
    kind = 'merge'

    def __init__(self, screen_id, title, names, lines_a, lines_b, label, suggest, bump):
        self.id = screen_id
        self.title = title
        self.names = list(names)
        self.blocks = merging.blocks(lines_a, lines_b)
        self.labels = [list(label)] if label else []
        self._suggest = suggest
        self._bump = bump
        # The AI's merge: None (not asked), or {'status': asking/done/failed, 'lines', 'notes', 'error'}
        self.ai = None
        self._result = None
        self._done = threading.Event()
        self.version = bump()

    def run(self):
        """Wait until the page saves the merge (its lines) or goes back (None)"""
        self._done.wait()
        return self._result

    def act(self, body):
        """What the page does: save (body['text']: the merged text), cancel, or ask the AI (suggest)"""
        action = body.get('action')
        if action == 'save' and isinstance(body.get('text'), str):
            self._finish(body['text'].split('\n'))
        elif action == 'cancel':
            self._finish(None)
        elif action == 'suggest' and self._suggest is not None and (self.ai is None or self.ai['status'] != 'asking'):
            self.ai = {'status': 'asking'}
            self.version = self._bump()
            threading.Thread(target=self._ask, daemon=True).start()

    def _ask(self):
        try:
            lines, notes = self._suggest()
            self.ai = {'status': 'done', 'lines': list(lines), 'notes': notes}
        except Exception as error:
            self.ai = {'status': 'failed', 'error': str(error)}
        self.version = self._bump()

    def _finish(self, result):
        if self._done.is_set():
            return
        self._result = result
        self._done.set()
        self.version = self._bump()

    def cancel(self):
        """End it as if the page went back (e.g. the daemon is stopping)"""
        self._finish(None)

    def meta(self):
        return {'kind': self.kind, 'id': self.id, 'title': self.title, 'labels': self.labels, 'names': self.names,
                'blocks': [{'same': block[1]} if block[0] == 'same' else {'a': block[1], 'b': block[2]}
                           for block in self.blocks],
                'canSuggest': self._suggest is not None}

    def state(self, since):
        return {'ai': self.ai, 'done': self._done.is_set()}
