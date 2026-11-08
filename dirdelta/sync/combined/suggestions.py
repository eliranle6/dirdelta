"""What the AI suggests doing with the combined tree's files (Suggestions), asked in the background
(Ctrl-I) while the user goes on, as the sort asks Claude where its files go: a batch at a time, on a
worker thread, each file's suggestion (or failure) shown as it comes, its arrow set by A. What a (the
user's request) says is kept here too."""
import collections
import threading

from dirdelta.claude import aiplan
from dirdelta.sync.combined import plan as plans

# What the AI is asked, of each batch
SUGGESTION = ("Suggest what to do with each of these files to sync the two replicas: which way each should "
              "go, or none where it's unclear (leave it out of the plan, saying why in the summary).")
# A batch: the files it may read at once
BATCH_SIZE = aiplan.MAX_FOCUS
# Why a file it left out is to be left as it is, when it didn't say
LEFT = "It suggests leaving it as it is."

# What the AI suggests for a file: its arrow (plans.TO_B, TO_A, or SKIP to leave it), and why
Suggestion = collections.namedtuple('Suggestion', ['state', 'reason'])


class Suggestions(object):
    """The AI's suggestions, and what it's asked now, by relpath, changed by the worker from its
    thread, under the lock. task_of(relpaths): the aiplan.Task to ask about them."""

    def __init__(self, task_of):
        self._task_of = task_of
        self.lock = threading.Lock()
        self._suggested = {}
        self._failed = {}
        # The files being asked about (queued, or in the batch asked now), the queue, and the worker
        self._asking = set()
        self._queue = collections.deque()
        self._worker = None
        # How many times the suggestions changed, so what shows them knows when to look again
        self.generation = 0

    def suggestion(self, relpath):
        return self._suggested.get(relpath)

    def failure(self, relpath):
        """Why the AI couldn't say what to do with the file, or None"""
        return self._failed.get(relpath)

    def is_asking(self, relpath):
        return relpath in self._asking

    def busy(self):
        """How many files it's asked about now"""
        return len(self._asking)

    def suggested_under(self, relpaths):
        """{relpath: Suggestion} of relpaths"""
        with self.lock:
            return {relpath: self._suggested[relpath] for relpath in relpaths if relpath in self._suggested}

    def set(self, relpath, state, reason):
        """What a (the user's request) said of the file"""
        with self.lock:
            self._suggested[relpath] = Suggestion(state, reason)
            self._failed.pop(relpath, None)
            self.generation += 1

    def ask_in_background(self, relpaths):
        """Ask the AI about the files at relpaths anew (what it said of them before is dropped), a
        batch at a time, on a thread of its own, while the user goes on"""
        with self.lock:
            for relpath in relpaths:
                if relpath in self._asking:
                    continue
                self._suggested.pop(relpath, None)
                self._failed.pop(relpath, None)
                self._asking.add(relpath)
                self._queue.append(relpath)
            self.generation += 1
            if self._queue and self._worker is None:
                self._worker = threading.Thread(target=self._work, daemon=True)
                self._worker.start()

    def wait(self):
        """Until the worker has asked about all that's queued (for tests, and quitting)"""
        worker = self._worker
        if worker is not None:
            worker.join()

    def _work(self):
        """Ask about the queued files, a batch at a time, until there are none (on the worker's thread:
        nothing is printed, as a picker may have the screen)"""
        while True:
            with self.lock:
                if not self._queue:
                    self._worker = None
                    return
                batch = [self._queue.popleft() for _ in range(min(BATCH_SIZE, len(self._queue)))]
            try:
                found, failed = self._ask(batch), {}
            except Exception as error:
                found, failed = {}, {relpath: str(error) or error.__class__.__name__ for relpath in batch}
            with self.lock:
                self._suggested.update(found)
                self._failed.update(failed)
                self._asking.difference_update(batch)
                self.generation += 1

    def _ask(self, batch):
        """{relpath: Suggestion} of the batch's files, as the AI answers (the ones it left out: to be
        left, as its summary says why)"""
        plan = aiplan.make(self._task_of(batch), SUGGESTION)
        found = {step.relpath: Suggestion(step.action, step.reason) for step in plan.steps}
        for said, why_not in plan.left_out:
            # What it said that can't be done (e.g. into a read-only replica: "ACTION RELPATH"): left,
            # saying so
            for relpath in batch:
                if said.endswith(' ' + relpath) and relpath not in found:
                    found[relpath] = Suggestion(plans.SKIP, "It suggested what can't be done (%s): %s" % (said, why_not))
        for relpath in batch:
            found.setdefault(relpath, Suggestion(plans.SKIP, plan.summary or LEFT))
        return found
