"""The combined tree's screen (CombinedSync): all the differences, what to do with each, then the plan
to confirm, and doing it"""

import threading

from dirdelta.known import replicanames
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync import view
from dirdelta.sync.combined import ai_showing
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import confirming
from dirdelta.sync.combined import diffing
from dirdelta.sync.combined import diffpane
from dirdelta.sync.combined import diffview
from dirdelta.sync.combined import doing
from dirdelta.sync.combined import keys_help
from dirdelta.sync.combined import showing
from dirdelta.sync.combined import suggestions
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import frontend
from dirdelta.ui import images
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text

CONFIRM_NO, CONFIRM_YES, CONFIRM_SURE = confirming.CONFIRM_NO, confirming.CONFIRM_YES, confirming.CONFIRM_SURE


class CombinedSync(showing.Showing, keys_help.KeysHelp, ai_showing.AIShowing, ask_ai.AskAI, diffpane.DiffPane):
    """One tree of everything that differs between replica_a and replica_b (at their paths): the files
    only one has (only_a, only_b: relpaths) and the ones both have that differ (changes: a
    differing.Changes, A's way), and the moved pairs among them (moved: see moved.find()), each put by
    the user in a state (what to do with it, all skipped at first), then done once the user confirms
    the plan. changes_log: as InteractiveDirSync's changes. chosen: the states it starts in ({relpath: state})."""

    def __init__(self, replica_a, replica_b, path_a, path_b, only_a, only_b, changes, changes_log=None, moved=None,
                 chosen=None):
        self.replica_a, self.replica_b = replica_a, replica_b
        self.path_a, self.path_b = path_a, path_b
        names = replicanames.short_names([path_a, path_b])
        self.name_a, self.name_b = names[path_a], names[path_b]
        self.changes = changes
        self.changes_log = changes_log
        self.moved = moved or {}
        self.grouped = plans.groups(only_a, only_b, changes, self.moved)
        # What the user chose so far, kept when they go back to the tree from the confirmation (and, given,
        # from before: the sync menu keeps it while they go back to it), of the files still here
        self.chosen = {relpath: state for relpath, state in (chosen or {}).items() if relpath in self.grouped}
        # The view of the differences its switch asked for, if it ended so (view.py), else None
        self.switch = None
        self.selected = None
        self._shown = None
        self.allowed = plans.allowed(self.replica_a, self.replica_b)
        # What the AI suggests (Ctrl-I, in the background, of a batch it may read; a's too); the
        # files put in the states it suggests (Ctrl-A): {relpath: (state, the time it was asked)}
        self.suggestions = suggestions.Suggestions(lambda batch: self._ai_task(batch, focus=batch))
        self._applied = {}
        self._apply_generation = 0
        # The diffs worked out (see DiffPane), and what makes the previews be sent at once
        self._diffs = {}
        self._wake = threading.Event()

    def run(self):
        """Until the user is done (or goes back): returns whether the replicas' files changed"""
        if not self.grouped:
            lines = ["%s and %s have the same files." % (self.name_a, self.name_b)]
            unverified = comparing.unverified_line(self.changes)
            if unverified:
                lines += ["", picker.unstyled(unverified)]
            messages.show("Nothing to do", lines, dryrun.label())
            return False
        frontend.show_replicas([(self.path_a, self.name_a), (self.path_b, self.name_b)])
        while True:
            # The states the tree starts in are the ones it ended in: what Ctrl-A set is in them
            self._applied.clear()
            picked = picker.pick_states(
                "%s ⇄ %s" % (self.name_a, self.name_b), plans.entries(self.grouped, self.allowed, self.chosen),
                plans.STATES, tabs=self._tabs(), header=self._header(), selected=self.selected,
                shown_as=self._shown_as, previews=self._send_previews,
                key_hints=self._key_hints(),
                help_lines=self._help_lines(), footer=self._footer(),
                keys=ask_ai.KEY + diffing.KEY + keys_help.BACK_KEY + view.SWITCH_KEY,
                on_selection=self._follow, notify_keys=ask_ai.SUGGEST_KEY + ask_ai.APPLY_KEY + diffview.KEY,
                on_notify=self._on_key, images=self._pictures())
            if picked is None:
                return False
            self.chosen, self.selected = picked.states, picked.selected
            if picked.key == keys_help.BACK_KEY:
                return False
            if picked.key == view.SWITCH_KEY:
                # Another view of the differences asked for (the page's, else all of them, acted on): viewing.py
                self.switch = view.requested(view.ALL, view.PLAN)
                return False
            if picked.key == diffing.KEY:
                diffing.show(self, self.selected)
                continue
            if picked.key == ask_ai.KEY:
                self._ask_ai()
                continue
            plan = plans.plan_of(self.chosen, self.grouped, self.moved)
            if plans.is_empty(plan) or not self._is_confirmed(plan):
                continue
            doing.do(plan, self.replica_a, self.replica_b, self.changes_log,
                     {self.replica_a: self.name_a, self.replica_b: self.name_b})
            return True

    def _pictures(self):
        """The tree's pictures (see pick_files()'s images): each file's from the replica that has it (A's, but
        for a file only in B), or None if neither replica's can be made"""
        of_a, of_b = images.of_replica(self.replica_a), images.of_replica(self.replica_b)
        if of_a is None and of_b is None:
            return None

        def picture(relpath, max_width, max_height):
            made = of_b if self.grouped.get(relpath) == plans.ONLY_B else of_a
            return made(relpath, max_width, max_height) if made is not None else None
        return picture

    def _on_key(self, key, selected):
        """A key that doesn't end the tree (on a thread of its own): Ctrl-I asks the AI about the
        selection's files, Ctrl-A sets the arrows it suggests there, Ctrl-T shows the diff's next view"""
        if key == ask_ai.SUGGEST_KEY:
            self._suggest(selected)
        elif key == ask_ai.APPLY_KEY:
            self._apply(selected)
        elif key == diffview.KEY:
            self._next_view()
        self._wake.set()

    def _is_confirmed(self, plan):
        """Whether the user says yes to the plan (removing files: and is sure): confirming.confirm()"""
        return confirming.confirm(plan, self.replica_a, self.replica_b, self.name_a, self.name_b)
