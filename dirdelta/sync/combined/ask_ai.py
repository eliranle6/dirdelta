"""Asking AI what to do with the combined tree's files (see aiplan.py): a, what the user types, whose
plan's steps set their arrows, for the user to review in the tree itself; Ctrl-I, its suggestions for
the selection's files, in the background (suggestions.py), whose arrows Ctrl-A sets (CombinedSync's)"""
from dirdelta.claude import aiplan
from dirdelta.matching import differing
from dirdelta.screens import aiplan_screen
from dirdelta.sync.combined import plan as plans
from dirdelta.util import text

KEY = aiplan_screen.KEY
# Ctrl-I (Tab, which treepicker leaves to it): the AI suggests what to do with the selection's files, in
# the background, as Ctrl-I asks Claude where an inbox's files go (suggestions.py); Ctrl-A sets the
# arrows it suggests, there and then
SUGGEST_KEY, SUGGEST_KEY_NAME = '\t', 'Ctrl-I'
APPLY_KEY, APPLY_KEY_NAME = '\x01', 'Ctrl-A'


class AskAI(object):
    """Asking the AI (CombinedSync's): what a (the user's request) plans sets the arrows of its steps,
    and is noted in suggestions, as Ctrl-I's are, which show in the previews, and ai_note below the
    tree"""
    ai_note = ''
    _last_instruction = ''

    def _under(self, selected):
        """The files at selected or under it (all of them on the root)"""
        selected = selected or ''
        return [relpath for relpath in self.grouped
                if not selected or relpath == selected or relpath.startswith(selected + '/')]

    def _ai_task(self, only=None, focus=()):
        """What to ask the AI about: each entry (or only those), what it is, and the two arrows, where
        they're allowed; focus: the files it may read (the user's on)"""
        allowed = self.allowed
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
        return aiplan.Task("These are the differences between two replicas of the same files, %s and %s, which "
                           "the person syncs: files only one has, and files both have that differ." % (name_a, name_b),
                           files, actions, focus=sorted(focus), fetch=self._local_path)

    def _local_path(self, relpath):
        """Where the entry's file is on this machine, to read (A's, else B's), or None"""
        for replica in (self.replica_a, self.replica_b):
            if replica.has_file(relpath):
                return replica.local_path(relpath)
        return None

    def _ask_ai(self):
        """a: ask the AI what the user types (about all the files, the selection's its focus), and set the
        arrows of its plan's steps, keeping the others as they were"""
        focus = sorted(self._under(self.selected)) if self.selected else []
        self._last_instruction, steps = aiplan_screen.ask(self._ai_task(focus=focus), self._last_instruction, review=False)
        if steps is None:
            return
        for step in steps:
            self.chosen[step.relpath] = step.action
            self.suggestions.set(step.relpath, step.action, step.reason)
        self.ai_note = ai_note(len(steps))

    def _suggest(self, selected):
        """Ctrl-I: ask the AI about the files at selected (or under it) in the background"""
        self.suggestions.ask_in_background(self._under(selected))

    def _apply(self, selected):
        """Ctrl-A: put the files at selected (or under it) in the states the AI suggests, in the tree
        that's shown (see shown_as())"""
        self._apply_generation += 1
        for relpath, suggestion in self.suggestions.suggested_under(self._under(selected)).items():
            self._applied[relpath] = (suggestion.state, self._apply_generation)


def ai_note(count):
    """The line below the tree after the AI's plan"""
    return "The AI set the arrows of %s (its reasons are in the right column): review them, then Enter" % (
        text.files(count),)
