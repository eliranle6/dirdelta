"""Both replicas' differences at once, checked and acted on (BothSides: view.py's ALL or MOVED, in its ACT mode): each
file where it is (only in A, only in B, in both and differing, moved), the checked ones copied to the replica that lacks
each, removed from where each is, or (a moved pair) moved to match, done at once once confirmed (as the combined tree's
plan is: confirming.py, doing.py); the tree again after, until the user goes back or switches the view"""
import os

from dirdelta.known import replicanames
from dirdelta.matching import differing
from dirdelta.sync import view
from dirdelta.sync.ways import differ_word
from dirdelta.sync.combined import confirming
from dirdelta.sync.combined import doing
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text

NOTHING = "Nothing: back to the files"
COPY, REMOVE, MOVE_IN_B, MOVE_IN_A = 'copy', 'remove', 'move in b', 'move in a'


class BothSides(object):
    def __init__(self, replica_a, replica_b, path_a, path_b, only_a, only_b, changes, moved, changes_log=None,
                 only_moved=False):
        """only_a, only_b: relpaths; changes: a differing.Changes; moved: {relpath only in A: its match only in B}; with
        only_moved, the moved pairs alone"""
        self.replica_a, self.replica_b = replica_a, replica_b
        names = replicanames.short_names([path_a, path_b])
        self.name_a, self.name_b = names[path_a], names[path_b]
        self.changes, self.moved, self.changes_log = changes, moved or {}, changes_log
        grouped = plans.groups(only_a, only_b, changes, self.moved)
        self.grouped = {relpath: group for relpath, group in grouped.items() if not only_moved or group == plans.MOVED}
        # The view of the differences its switch asked for, if it ended so (view.py), else None
        self.switch = None

    def run(self):
        """Until the user goes back (or switches the view): whether the replicas' files changed"""
        picked, selected = [], None
        relpaths = sorted(self.grouped, key=lambda relpath: relpath.split('/'))
        if not relpaths:
            messages.show("Nothing to do", ["%s and %s have the same files." % (self.name_a, self.name_b)], dryrun.label())
            return False
        while True:
            chosen = picker.pick_files(
                "%s ⇄ %s" % (self.name_a, self.name_b), relpaths, picked=picked, selected=selected,
                header="Check files, then choose what to do with them: each where it is.", shown_as=self._shown_as,
                keys=view.SWITCH_KEY, enter_picks_selection=True,
                key_hints=[('Enter', 'choose what to do'), (view.SWITCH_KEY_NAME, 'plan them instead')],
                none_picked_key_hints=[('Enter', 'Check & choose what to do')])
            if chosen is None:
                return False
            selected = chosen.selected
            if chosen.key == view.SWITCH_KEY:
                self.switch = view.requested(view.ALL, view.ACT)
                return False
            if not chosen.files:
                continue
            plan = self._plan_of(chosen.files)
            if plan is None or not confirming.confirm(plan, self.replica_a, self.replica_b, self.name_a, self.name_b):
                picked = chosen.files
                continue
            doing.do(plan, self.replica_a, self.replica_b, self.changes_log,
                     {self.replica_a: self.name_a, self.replica_b: self.name_b})
            if not dryrun.DRYRUN:
                return True
            # (A dry run changed nothing: the same files, none checked)
            picked = []

    def _shown_as(self):
        """Each file's name and where it is: only in one, in both and differing (its tag), or moved (where B has it)"""
        shown = {}
        for relpath, group in self.grouped.items():
            name = os.path.basename(relpath)
            if group == plans.DIFFER:
                shown[relpath] = picker.styled([(name + differing.styled_tag(self.changes[relpath], (self.name_a, self.name_b)), None)])
            elif group == plans.MOVED:
                shown[relpath] = picker.styled([(name, None), ("  moved: in %s at %s" % (self.name_b, self.moved[relpath]), plans.MOVE_COLOR)])
            else:
                shown[relpath] = picker.styled([(name, None), ("  only in %s" % (self.name_a if group == plans.ONLY_A else self.name_b,), 'grey')])
        return shown

    def _plan_of(self, relpaths):
        """What to do with the checked files, asked: a plans.Plan, or None (nothing)"""
        by_group = {group: [relpath for relpath in relpaths if self.grouped.get(relpath) == group] for group in
                    (plans.ONLY_A, plans.ONLY_B, plans.DIFFER, plans.MOVED)}
        only_a, only_b, differ, moved = (by_group[group] for group in (plans.ONLY_A, plans.ONLY_B, plans.DIFFER, plans.MOVED))
        one_side = len(only_a) + len(only_b)
        files = text.files
        options = [picker.Option(NOTHING, NOTHING)]
        where = ", ".join(part for part in ("%d to %s" % (len(only_a), self.name_b) if only_a else '',
                                            "%d to %s" % (len(only_b), self.name_a) if only_b else '') if part)
        options.append(picker.Option(COPY, "Copy %s to where %s missing (%s)" % (files(one_side), "it's" if one_side == 1 else "they're", where))
                       if one_side else picker.Option(COPY, "Copy", picker.Disabled("Copy: can't: none of them is only on one side")))
        where = ", ".join(part for part in ("%d from %s" % (len(only_a), self.name_a) if only_a else '',
                                            "%d from %s" % (len(only_b), self.name_b) if only_b else '') if part)
        options.append(picker.Option(REMOVE, "Remove %s from where %s (%s)" % (files(one_side), "it is" if one_side == 1 else "they are", where))
                       if one_side else picker.Option(REMOVE, "Remove", picker.Disabled("Remove: can't: none of them is only on one side")))
        if moved:
            them = "it" if len(moved) == 1 else "them"
            options.append(picker.Option(MOVE_IN_B, "Move %s in %s to where %s has %s" % (files(len(moved)), self.name_b, self.name_a, them)))
            options.append(picker.Option(MOVE_IN_A, "Move %s in %s to where %s has %s" % (files(len(moved)), self.name_a, self.name_b, them)))
        lines = ["%s checked: %s." % (files(len(relpaths)), ", ".join(part for part in (
            "%d only in %s" % (len(only_a), self.name_a) if only_a else '', "%d only in %s" % (len(only_b), self.name_b) if only_b else '',
            "%d that %s" % (len(differ), differ_word(len(differ))) if differ else '', "%d moved" % (len(moved),) if moved else '') if part))]
        if differ:
            lines.append("The ones that differ are left as they are: which version wins is chosen with ⇒ ⇐ (Plan).")
        answer = picker.pick_option(options, header='\n'.join(lines), title="What to do")
        if answer == COPY:
            return plans.Plan(copy_to_b=only_a, copy_to_a=only_b, replace_b=[], replace_a=[], remove_from_a=[], remove_from_b=[])
        if answer == REMOVE:
            return plans.Plan(copy_to_b=[], copy_to_a=[], replace_b=[], replace_a=[], remove_from_a=only_a, remove_from_b=only_b)
        if answer == MOVE_IN_B:
            return plans.Plan([], [], [], [], [], [], move_in_b=[(self.moved[relpath], relpath) for relpath in moved])
        if answer == MOVE_IN_A:
            return plans.Plan([], [], [], [], [], [], move_in_a=[(relpath, self.moved[relpath]) for relpath in moved])
        return None
