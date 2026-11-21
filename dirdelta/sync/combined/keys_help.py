"""The combined tree's keys row, and its ? help: what its marks, its keys and its tags mean
(CombinedSync's)"""
from dirdelta.sync.combined import ai_showing
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import diffing
from dirdelta.sync.combined import diffview
from dirdelta.sync.combined import plan as plans

# Back to the sync menu, keeping the marks (q drops them: treepicker quits without saying them); the web
# version's Back is this
BACK_KEY, BACK_KEY_NAME = '\x11', 'Ctrl-Q'


class KeysHelp(object):
    """The keys row and the help (CombinedSync's)"""

    def _key_hints(self):
        return [(ask_ai.SUGGEST_KEY_NAME, "AI suggests"), (ask_ai.APPLY_KEY_NAME, "set AI's arrows"),
                (plans.TO_B_KEY, "⇒ %s" % (self.name_b,)), (plans.TO_A_KEY, "⇐ %s" % (self.name_a,)),
                (plans.SKIP_KEY, "skip: leave as is"), (diffing.KEY_NAME, "diff"), (ask_ai.KEY, "ask AI"),
                (BACK_KEY_NAME, "back, keeping the marks")]

    def _help_lines(self):
        return ["What each mark does:",
                "  (none)  skip: leave the file as it is, nothing's done with it (every file starts so; s, or "
                "Space until it comes back)",
                "  ⇒  green: copy %s's file to %s; yellow: %s's version replaces %s's" % (self.name_a, self.name_b,
                                                                                        self.name_a, self.name_b),
                "  ⇐  green: copy %s's file to %s; yellow: %s's version replaces %s's" % (self.name_b, self.name_a,
                                                                                        self.name_b, self.name_a),
                "  x  red: remove the file (only one has it)",
                "  ⇒ ⇐ cyan: a moved file (the same contents at another path in %s): move %s's to where %s has "
                "it, or %s's to where %s has it" % (self.name_b, self.name_b, self.name_a, self.name_a, self.name_b),
                "  *  a dir whose files are in different states",
                "Esc puts them all back to skipped.",
                "The AI:",
                "  %-17s%s" % (ask_ai.SUGGEST_KEY_NAME, "the AI works out what to do with the selected file (a dir: its "
                               "files) in the background, while you go on: a tag after each "
                               "name says what it suggests, the right column why"),
                "  %-17s%s" % (ask_ai.APPLY_KEY_NAME, "set the arrows of the selected file (a dir: its files) as the "
                               "AI suggests"),
                "  %-17s%s" % (ask_ai.KEY, "ask AI anything about all the files, or say what to do: its plan sets "
                               "the arrows"),
                "  %-24s%s" % (ai_showing.LOOKING, "the AI is working out what to do with it"),
                "  %-24s%s" % ("[ai: ⇒ %s]" % (self.name_b,), "what the AI suggests (Ctrl-A sets it)"),
                "Diff:",
                "  %-17s%s" % (diffview.KEY_NAME, "show the changes, or either whole version: the next view of the right "
                               "column's diff of the selected differing text file, side by side, as diff -u, %s's version, %s's version (Ctrl-W l scrolls it, "
                               "Ctrl-P hides the column)" % (self.name_a, self.name_b)),
                "  %-17s%s" % (diffing.KEY_NAME, "the selected file's whole diff, %s's version against %s's, in less "
                               "(q: back); text files only" % (self.name_a, self.name_b))]
