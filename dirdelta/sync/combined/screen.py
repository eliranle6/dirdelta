"""The combined tree's screen (CombinedSync): all the differences, what to do with each, then the plan
to confirm, and doing it"""
import os

from dirdelta.known import replicanames
from dirdelta.matching import differing
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import doing
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text

# The most files of each thing the confirmation lists
MAX_FILES_LISTED = 5

CONFIRM_NO, CONFIRM_YES, CONFIRM_SURE = "No, back to the tree", "Yes, do it", "Yes, I'm sure"


class CombinedSync(object):
    """One tree of everything that differs between replica_a and replica_b (at their paths): the files
    only one has (only_a, only_b: relpaths) and the ones both have that differ (changes: a
    differing.Changes, A's way), each put by the user in a state (what to do with it, all skipped at
    first), then done once the user confirms the plan. changes_log: as InteractiveDirSync's changes."""

    def __init__(self, replica_a, replica_b, path_a, path_b, only_a, only_b, changes, changes_log=None):
        self.replica_a, self.replica_b = replica_a, replica_b
        names = replicanames.short_names([path_a, path_b])
        self.name_a, self.name_b = names[path_a], names[path_b]
        self.changes = changes
        self.changes_log = changes_log
        self.grouped = plans.groups(only_a, only_b, changes)
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
                shown_as=self._shown_as, previews=self._previews if self.changes else None, key_hints=self._key_hints(),
                help_lines=self._help_lines(), footer=comparing.unverified_line(self.changes))
            if picked is None:
                return False
            self.chosen, self.selected = picked.states, picked.selected
            plan = plans.plan_of(self.chosen, self.grouped)
            if plans.is_empty(plan) or not self._is_confirmed(plan):
                continue
            doing.do(plan, self.replica_a, self.replica_b, self.changes_log)
            return True

    def _header(self):
        return ("Everything that differs between %s and %s: choose what to do with each (all skipped at first).\n"
                "→ makes %s like %s, ← makes %s like %s: copying, replacing or removing files." %
                (self.name_a, self.name_b, self.name_b, self.name_a, self.name_a, self.name_b))

    def _tabs(self):
        """All, then each group, if it has files"""
        counts = {group: list(self.grouped.values()).count(group) for group in (plans.ONLY_A, plans.ONLY_B, plans.DIFFER)}
        tabs = [picker.Tab("All")]
        for group, title in ((plans.ONLY_A, "Only in %s" % (self.name_a,)), (plans.ONLY_B, "Only in %s" % (self.name_b,)),
                             (plans.DIFFER, "Differ")):
            if counts[group]:
                tabs.append(picker.Tab(title, (group,)))
        return tabs

    def _key_hints(self):
        return [(plans.TO_B_KEY, "→ %s" % (self.name_b,)), (plans.TO_A_KEY, "← %s" % (self.name_a,)),
                (plans.SKIP_KEY, "skip")]

    def _help_lines(self):
        return ["",
                "What each mark does:",
                "  →  green: copy %s's file to %s; yellow: %s's version replaces %s's" % (self.name_a, self.name_b,
                                                                                        self.name_a, self.name_b),
                "  ←  green: copy %s's file to %s; yellow: %s's version replaces %s's" % (self.name_b, self.name_a,
                                                                                        self.name_b, self.name_a),
                "  x  red: remove the file (only one has it)",
                "  *  a dir whose files are in different states",
                "Esc puts them all back to skipped."]

    def _shown_as(self):
        """Each file's name, and where it is: only in one, or in both, differing (its tag); worked out
        once"""
        if self._shown is not None:
            return self._shown
        shown = self._shown = {}
        for relpath, group in self.grouped.items():
            name = os.path.basename(relpath)
            if group == plans.DIFFER:
                shown[relpath] = name + differing.styled_tag(self.changes[relpath], (self.name_a, self.name_b))
            else:
                shown[relpath] = picker.styled([(name, None), ("  only in %s" % (
                    self.name_a if group == plans.ONLY_A else self.name_b,), 'grey')])
        return shown

    def _previews(self, send):
        """The files that differ's previews: both versions, and what each arrow does with them"""
        width = max(len(self.name_a), len(self.name_b)) + 2
        lines_of = {}
        for relpath, change in self.changes.items():
            lines = [picker.styled([("%s Two versions" % (differing.mark(change),), 'bold,' + differing.style(change))])]
            lines += differing.versions_lines(change, (self.name_a + ":").ljust(width), (self.name_b + ":").ljust(width))
            lines.append("")
            for arrow, src, dst in (("→", self.replica_a, self.replica_b), ("←", self.replica_b, self.replica_a)):
                names = {self.replica_a: self.name_a, self.replica_b: self.name_b}
                lines.append("%s %s's replaces %s's (%s)" % (
                    arrow, names[src], names[dst], "to the trash" if replica_ops.is_local(dst) else "Drive keeps it")
                    if replica_ops.can_copy(src, dst) else "%s can't be done: %s" % (
                        arrow, "%s is read-only" % (names[dst],) if not replica_ops.is_writable(dst)
                        else "dirdelta doesn't copy within Drive"))
            lines_of[relpath] = lines
        send(lines_of, default=[])

    def _is_confirmed(self, plan):
        """Whether the user says yes to the plan (removing files: and is sure)"""
        lines = ["Do this?"]
        for line, relpaths in zip(plans.summary(plan, self.name_a, self.name_b), [relpaths for relpaths in plan if relpaths]):
            lines.append("  " + line + ":")
            lines += text.listed(["      %s" % (relpath,) for relpath in relpaths], MAX_FILES_LISTED)
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
