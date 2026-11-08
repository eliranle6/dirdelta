"""Asking AI what to do with the combined tree's files (see aiplan.py): its plan's steps set their
arrows, for the user to review in the tree itself (CombinedSync's)"""
from dirdelta.claude import aiplan
from dirdelta.matching import differing
from dirdelta.screens import aiplan_screen
from dirdelta.sync.combined import plan as plans
from dirdelta.util import text

KEY = aiplan_screen.KEY
# Ctrl-I (Tab, which treepicker leaves to it): the AI suggests what to do with each file, without
# being told anything, as Ctrl-I asks Claude where an inbox's files go
SUGGEST_KEY = '\t'
SUGGEST_KEY_NAME = 'Ctrl-I'
SUGGESTION = ("Suggest what to do with each of these files to sync the two replicas: which way each should "
              "go, or none where it's unclear, for me to review.")


class AskAI(object):
    """The AI's plans (CombinedSync's): ai_reasons ({relpath: (the arrow it suggests, SKIP to leave the
    file, and why)}) are shown in the previews, and ai_note below the tree. What a (the user's
    request) says replaces them; what Ctrl-I says of the selection's files is added to them."""
    ai_reasons = None
    ai_note = ''
    _last_instruction = ''

    def _in_selection(self):
        """The files under the selection (or it), all of them on the root"""
        selected = self.selected or ''
        return [relpath for relpath in self.grouped
                if not selected or relpath == selected or relpath.startswith(selected + '/')]

    def _ai_task(self, allowed, only=None):
        """What to ask the AI about: each entry (or only those), what it is, and the two arrows, where
        they're allowed"""
        name_a, name_b = self.name_a, self.name_b
        notes = {plans.ONLY_A: "only in %s" % (name_a,), plans.ONLY_B: "only in %s" % (name_b,)}
        files = []
        for relpath, group in sorted(self.grouped.items(), key=lambda item: item[0].split('/')):
            if only is not None and relpath not in only:
                continue
            if group == plans.DIFFER:
                note = "in both, different: %s" % (differing.tag(self.changes[relpath], (name_a, name_b)),)
            elif group == plans.MOVED:
                note = "in %s here, and the same contents in %s at %s (moved)" % (name_a, name_b, self.moved[relpath])
            else:
                note = notes[group]
            replica = self.replica_b if group == plans.ONLY_B else self.replica_a
            files.append(aiplan.File(relpath, replica.file_size(relpath), note))

        def check(state):
            return lambda relpath, target: (None if state in allowed.get(self.grouped.get(relpath), ()) else
                                            "it can't be done there (read-only)")
        actions = [aiplan.Action(plans.TO_B, "Make %s like %s" % (name_b, name_a),
                                 "make %s like %s for this file: copy %s's file to %s if only %s has it, remove %s's "
                                 "if only %s has it, replace %s's version with %s's if they differ, move %s's to "
                                 "%s's path if it's moved." % ((name_b, name_a, name_a, name_b, name_a, name_b, name_b,
                                                                name_b, name_a, name_b, name_a)),
                                 check=check(plans.TO_B)),
                   aiplan.Action(plans.TO_A, "Make %s like %s" % (name_a, name_b),
                                 "make %s like %s for this file: copy %s's file to %s if only %s has it, remove %s's "
                                 "if only %s has it, replace %s's version with %s's if they differ, move %s's to "
                                 "%s's path if it's moved." % ((name_a, name_b, name_b, name_a, name_b, name_a, name_a,
                                                                name_a, name_b, name_a, name_b)),
                                 check=check(plans.TO_A))]
        focus = self._in_selection() if self.selected else []
        return aiplan.Task("These are the differences between two replicas of the same files, %s and %s, which "
                           "the person syncs: files only one has, and files both have that differ." % (name_a, name_b),
                           files, actions, focus=sorted(focus), fetch=self._local_path)

    def _local_path(self, relpath):
        """Where the entry's file is on this machine, to read (A's, else B's), or None"""
        for replica in (self.replica_a, self.replica_b):
            if replica.has_file(relpath):
                return replica.local_path(relpath)
        return None

    def _ask_ai(self, allowed, suggest=False):
        """Ask the AI (what the user types, or with suggest, SUGGESTION), and set the arrows of its plan's
        steps (allowed: plans.allowed()'s), keeping the others as they were"""
        only = self._in_selection() if suggest else None
        self._last_instruction, steps = aiplan_screen.ask(self._ai_task(allowed, only), self._last_instruction,
                                                          review=False, instruction=SUGGESTION if suggest else None)
        if steps is None:
            return
        if not suggest:
            self.ai_reasons = {}
        self.ai_reasons = dict(self.ai_reasons or {})
        # What it said of each file it was asked about: the ones it left are to be left (skipped)
        for relpath in only or []:
            self.ai_reasons[relpath] = (plans.SKIP, "It suggests leaving it as it is.")
        for step in steps:
            self.chosen[step.relpath] = step.action
            self.ai_reasons[step.relpath] = (step.action, step.reason)
        self.ai_note = ai_note(len(steps))


def ai_note(count):
    """The line below the tree after the AI's plan"""
    return "The AI set the arrows of %s (its reasons are in the right column): review them, then Enter" % (
        text.files(count),)
