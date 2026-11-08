"""What the combined tree shows: its header, tabs, footer, keys and help, each file's tag, and the
previews (CombinedSync's)"""
import collections
import os

from dirdelta.inbox.formatting import grey_line, preview_title, wrapped
from dirdelta.matching import differing
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import diffing
from dirdelta.sync.combined import diffview
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker


class Showing(object):
    """What the tree is shown with (CombinedSync's)"""

    def _header(self):
        return "What differs. Mark each file: ⇒ makes %s like %s, ⇐ makes %s like %s." % (
            self.name_b, self.name_a, self.name_a, self.name_b)

    def _tabs(self):
        """All, then each group, if it has files"""
        counts = collections.Counter(self.grouped.values())
        tabs = [picker.Tab("All")]
        for group, title in ((plans.ONLY_A, "Only in %s" % (self.name_a,)), (plans.ONLY_B, "Only in %s" % (self.name_b,)),
                             (plans.DIFFER, "Differ"), (plans.MOVED, "Moved")):
            if counts[group]:
                tabs.append(picker.Tab(title, (group,)))
        return tabs

    def _footer(self):
        """Below the tree: the files taken as the same, unverified, and what the AI did"""
        lines = [comparing.unverified_line(self.changes)]
        if self.ai_note:
            lines.append(picker.styled([("✦ " + self.ai_note, 'magenta')]))
        return '\n'.join(line for line in lines if line)

    def _key_hints(self):
        return [(ask_ai.SUGGEST_KEY_NAME, "AI suggests"), (ask_ai.KEY, "ask AI"), (plans.TO_B_KEY, "⇒ %s" % (self.name_b,)),
                (plans.TO_A_KEY, "⇐ %s" % (self.name_a,)), (plans.SKIP_KEY, "skip: leave as is"),
                (diffing.KEY, "diff")]

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
                "More on its keys:",
                "  %-17s%s" % (ask_ai.SUGGEST_KEY_NAME, "the AI suggests what to do with the selected file (a dir: its "
                               "files) and sets their arrows; the right column says what and why"),
                "  %-17s%s" % (ask_ai.KEY, "ask AI anything about all the files, or say what to do: its plan sets "
                               "the arrows"),
                "  %-17s%s" % (diffview.KEY, "the next view of the right column's diff of the selected differing text "
                               "file: side by side, as diff -u, %s's version, %s's version (Ctrl-W l scrolls it, "
                               "Ctrl-P hides the column)" % (self.name_a, self.name_b)),
                "  %-17s%s" % (diffing.KEY, "the selected file's diff, %s's version against %s's, in less (q: back); "
                               "text files only" % (self.name_a, self.name_b))]

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
            elif group == plans.MOVED:
                shown[relpath] = picker.styled([(name, None), ("  moved: in %s at %s" % (self.name_b, self.moved[relpath]),
                                                               plans.MOVE_COLOR)])
            else:
                shown[relpath] = picker.styled([(name, None), ("  only in %s" % (
                    self.name_a if group == plans.ONLY_A else self.name_b,), 'grey')])
        return shown

    def _previews(self, send):
        """Every file's preview (see _file_preview()); the selected differing one's with its diff
        (_follow())"""
        send({relpath: self._file_preview(relpath) for relpath in self.grouped},
             default=["", picker.styled([("Recommendation:", 'bold')]), grey_line("  Ctrl-I asks AI about its files")])

    def _file_preview(self, relpath):
        """A file's preview: a differing file's versions and what each arrow does with them, a moved
        one's other path, or which one has it; then what the AI suggests for it, and why, as the
        sort's column shows Claude's recommendation"""
        group = self.grouped[relpath]
        if group == plans.DIFFER:
            change = self.changes[relpath]
            width = max(len(self.name_a), len(self.name_b)) + 2
            lines = [picker.styled([("%s Two versions" % (differing.mark(change),), 'bold,' + differing.style(change))])]
            lines += differing.versions_lines(change, (self.name_a + ":").ljust(width), (self.name_b + ":").ljust(width))
            lines.append("")
            names = {self.replica_a: self.name_a, self.replica_b: self.name_b}
            for arrow, src, dst in (("⇒", self.replica_a, self.replica_b), ("⇐", self.replica_b, self.replica_a)):
                lines.append("%s %s's replaces %s's (%s)" % (
                    arrow, names[src], names[dst], replica_ops.discarded_to(dst) if replica_ops.is_local(dst) else "Drive keeps it")
                    if replica_ops.can_copy(src, dst) else "%s can't be done: %s" % (
                        arrow, "%s is read-only" % (names[dst],) if not replica_ops.is_writable(dst)
                        else "dirdelta doesn't copy within Drive"))
        elif group == plans.MOVED:
            lines = [picker.styled([("↔ Moved", 'bold,' + plans.MOVE_COLOR)]),
                     "The same contents are in %s at" % (self.name_b,), "  " + self.moved[relpath], "",
                     "⇒ moves %s's there to here" % (self.name_b,), "⇐ moves this one there"]
        else:
            lines = [picker.styled([(os.path.basename(relpath), 'bold')]),
                     "Only in %s" % (self.name_a if group == plans.ONLY_A else self.name_b,)]
        return lines + self._recommendation_lines(relpath)

    def _recommendation_lines(self, relpath):
        """What the AI suggests for the file, and why, or how to ask it"""
        if relpath not in (self.ai_reasons or {}):
            return ["", picker.styled([("Recommendation:", 'bold')]), grey_line("  Ctrl-I asks AI")]
        state, reason = self.ai_reasons[relpath]
        what = {plans.TO_B: "⇒ make %s like %s" % (self.name_b, self.name_a),
                plans.TO_A: "⇐ make %s like %s" % (self.name_a, self.name_b)}.get(state, "skip: leave it as it is")
        return (["", preview_title("Recommendation (ai):", 'magenta')] + wrapped(what, "  ") + [""] +
                wrapped(reason or "(it didn't say why)", "  "))
