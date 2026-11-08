"""The combined tree's screen (CombinedSync): all the differences, what to do with each, then the plan
to confirm, and doing it"""

from dirdelta.known import replicanames
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import diffing
from dirdelta.sync.combined import doing
from dirdelta.sync.combined import showing
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text

# The most files of each thing the confirmation lists
MAX_FILES_LISTED = 5

CONFIRM_NO, CONFIRM_YES, CONFIRM_SURE = "No, back to the tree", "Yes, do it", "Yes, I'm sure"


class CombinedSync(showing.Showing, ask_ai.AskAI):
    """One tree of everything that differs between replica_a and replica_b (at their paths): the files
    only one has (only_a, only_b: relpaths) and the ones both have that differ (changes: a
    differing.Changes, A's way), and the moved pairs among them (moved: see moved.find()), each put by
    the user in a state (what to do with it, all skipped at first), then done once the user confirms
    the plan. changes_log: as InteractiveDirSync's changes."""

    def __init__(self, replica_a, replica_b, path_a, path_b, only_a, only_b, changes, changes_log=None, moved=None):
        self.replica_a, self.replica_b = replica_a, replica_b
        names = replicanames.short_names([path_a, path_b])
        self.name_a, self.name_b = names[path_a], names[path_b]
        self.changes = changes
        self.changes_log = changes_log
        self.moved = moved or {}
        self.grouped = plans.groups(only_a, only_b, changes, self.moved)
        # What the user chose so far, kept when they go back to the tree from the confirmation
        self.chosen = {}
        self.selected = None
        self._shown = None

    def run(self):
        """Until the user is done (or goes back): returns whether the replicas' files changed"""
        if not self.grouped:
            lines = ["%s and %s have the same files." % (self.name_a, self.name_b)]
            unverified = comparing.unverified_line(self.changes)
            if unverified:
                lines += ["", picker.unstyled(unverified)]
            messages.show("Nothing to do", lines, dryrun.label())
            return False
        allowed = plans.allowed(self.replica_a, self.replica_b)
        while True:
            picked = picker.pick_states(
                "%s ⇄ %s" % (self.name_a, self.name_b), plans.entries(self.grouped, allowed, self.chosen),
                plans.STATES, tabs=self._tabs(), header=self._header(), selected=self.selected,
                shown_as=self._shown_as, previews=self._previews,
                key_hints=self._key_hints(),
                help_lines=self._help_lines(), footer=self._footer(), keys=ask_ai.KEY + ask_ai.SUGGEST_KEY + diffing.KEY)
            if picked is None:
                return False
            self.chosen, self.selected = picked.states, picked.selected
            if picked.key == diffing.KEY:
                diffing.show(self, self.selected)
                continue
            if picked.key in (ask_ai.KEY, ask_ai.SUGGEST_KEY):
                self._ask_ai(allowed, suggest=picked.key == ask_ai.SUGGEST_KEY)
                continue
            plan = plans.plan_of(self.chosen, self.grouped, self.moved)
            if plans.is_empty(plan) or not self._is_confirmed(plan):
                continue
            doing.do(plan, self.replica_a, self.replica_b, self.changes_log)
            return True

    def _is_confirmed(self, plan):
        """Whether the user says yes to the plan (removing files: and is sure)"""
        lines = ["Do this?"]
        for line, items in plans.summary(plan, self.name_a, self.name_b):
            lines.append("  " + line + ":")
            lines += text.listed(["      %s" % (item,) for item in items], MAX_FILES_LISTED)
        for replica, name, relpaths in ((self.replica_b, self.name_b, plan.replace_b),
                                        (self.replica_a, self.name_a, plan.replace_a)):
            if relpaths:
                lines.append("%s's versions replaced go %s." % (name, "to the trash" if replica_ops.is_local(replica)
                                                                else "to Drive's older versions"))
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        label = ('SYNC', 'blue')
        if picker.pick_option([CONFIRM_NO, CONFIRM_YES], header='\n'.join(lines), title="Sure?", label=label) != CONFIRM_YES:
            return False
        nr_removed = plans.removals(plan)
        if not nr_removed:
            return True
        sure = "Are you sure? %s will be removed (a local replica's to the trash, Drive's to its trash)." % (
            text.files(nr_removed),)
        return picker.pick_option([CONFIRM_NO, CONFIRM_SURE], header=sure, title="Sure?", label=label) == CONFIRM_SURE
