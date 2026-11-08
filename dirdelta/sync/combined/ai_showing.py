"""What the combined tree shows of the AI's suggestions (CombinedSync's), as the sort shows Claude's:
a tag after a file's name (or that it's being asked about), the status on the bottom line, and the
recommendation in the right column, of a file or a dir's"""
import collections

from dirdelta.inbox.formatting import grey_line, preview_title, wrapped
from dirdelta.screens import hashes_screen
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker
from dirdelta.util import text

AI_STYLE = 'magenta'
TITLE = "Recommendation (ai):"
LOOKING = "(AI is looking at it...)"


class AIShowing(object):
    """The AI's suggestions, shown (CombinedSync's)"""

    def _what(self, state):
        """What a suggested state does, in words"""
        return {plans.TO_B: "⇒ make %s like %s" % (self.name_b, self.name_a),
                plans.TO_A: "⇐ make %s like %s" % (self.name_a, self.name_b)}.get(state, "leave it as it is")

    def _ai_tag(self, relpath):
        """(text, style) after the file's name: what the AI suggests, that it's being asked, or that
        it couldn't say; or None"""
        suggestions = self.suggestions
        if suggestions.is_asking(relpath):
            return (LOOKING, 'grey')
        suggestion = suggestions.suggestion(relpath)
        if suggestion is not None:
            arrow = {plans.TO_B: "⇒ %s" % (self.name_b,), plans.TO_A: "⇐ %s" % (self.name_a,)}.get(suggestion.state, "leave it")
            return ("[ai: %s]" % (arrow,), AI_STYLE)
        if suggestions.failure(relpath) is not None:
            return ("[ai: couldn't say]", 'red')
        return None

    def _ai_status(self):
        """The bottom line's status, as the sort's: how far hashing the local replicas got, and the
        AI's work (always sent, so it's cleared once there's none)"""
        busy = self.suggestions.busy()
        failed = len([relpath for relpath in self.grouped if self.suggestions.failure(relpath) is not None])
        parts = ([("AI: asking about %s" % (text.files(busy),), AI_STYLE)] if busy else
                 [("AI: couldn't say what to do with %s" % (text.files(failed),), 'red')] if failed else [])
        return hashes_screen.picker_status([self.replica_a, self.replica_b], parts)

    def _recommendation_lines(self, relpath):
        """What the AI suggests for the file, and why, or that it's working it out, or how to ask it"""
        suggestions = self.suggestions
        if suggestions.is_asking(relpath):
            return ["", preview_title(TITLE, AI_STYLE), grey_line("  The AI is working it out...")]
        suggestion = suggestions.suggestion(relpath)
        if suggestion is not None:
            return (["", preview_title(TITLE, AI_STYLE)] + wrapped(self._what(suggestion.state), "  ") + [""] +
                    wrapped(suggestion.reason or "(it didn't say why)", "  ") +
                    [grey_line("  %s sets its arrow so" % (ask_ai.APPLY_KEY_NAME,))])
        if suggestions.failure(relpath) is not None:
            return ["", preview_title(TITLE + " failed", 'red')] + wrapped(suggestions.failure(relpath), "  ")
        return ["", picker.styled([("Recommendation:", 'bold')]), grey_line("  %s asks AI" % (ask_ai.SUGGEST_KEY_NAME,))]

    def _dir_lines(self, dirpath, relpaths):
        """A dir's preview (its files: relpaths): how many, and what the AI suggests for them, in all"""
        lines = [picker.styled([("Dir: ", 'bold'), (text.files(len(relpaths)), None)])]
        asking = [relpath for relpath in relpaths if self.suggestions.is_asking(relpath)]
        suggested = self.suggestions.suggested_under(relpaths)
        if not asking and not suggested:
            return lines + ["", picker.styled([("Recommendation:", 'bold')]),
                            grey_line("  %s asks AI about its files" % (ask_ai.SUGGEST_KEY_NAME,))]
        lines += ["", preview_title(TITLE, AI_STYLE)]
        counts = collections.Counter(suggestion.state for suggestion in suggested.values())
        for state in (plans.TO_B, plans.TO_A, plans.SKIP):
            if counts[state]:
                lines += wrapped("%s: %s" % (self._what(state), text.files(counts[state])), "  ")
        if asking:
            lines.append(grey_line("  Working out %s..." % (text.files(len(asking)),)))
        if suggested:
            lines.append(grey_line("  %s sets their arrows so" % (ask_ai.APPLY_KEY_NAME,)))
        return lines
