"""What the combined tree shows: its header, tabs, footer, keys and help, each file's tag, and the
previews (CombinedSync's)"""
import collections
import os

from dirdelta.matching import differing
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker


class Showing(object):
    """What the tree is shown with (CombinedSync's)"""

    def _header(self):
        return ("Everything that differs between %s and %s: choose what to do with each (all skipped at first).\n"
                "→ makes %s like %s, ← makes %s like %s: copying, replacing, moving or removing files." %
                (self.name_a, self.name_b, self.name_b, self.name_a, self.name_a, self.name_b))

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
        return [(ask_ai.KEY, "ask AI"), (plans.TO_B_KEY, "→ %s" % (self.name_b,)), (plans.TO_A_KEY, "← %s" % (self.name_a,)),
                (plans.SKIP_KEY, "skip")]

    def _help_lines(self):
        return ["",
                "What each mark does:",
                "  →  green: copy %s's file to %s; yellow: %s's version replaces %s's" % (self.name_a, self.name_b,
                                                                                        self.name_a, self.name_b),
                "  ←  green: copy %s's file to %s; yellow: %s's version replaces %s's" % (self.name_b, self.name_a,
                                                                                        self.name_b, self.name_a),
                "  x  red: remove the file (only one has it)",
                "  → ← cyan: a moved file (the same contents at another path in %s): move %s's to" % (self.name_b, self.name_b),
                "      where %s has it, or %s's to where %s has it" % (self.name_a, self.name_a, self.name_b),
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
            elif group == plans.MOVED:
                shown[relpath] = picker.styled([(name, None), ("  moved: in %s at %s" % (self.name_b, self.moved[relpath]),
                                                               plans.MOVE_COLOR)])
            else:
                shown[relpath] = picker.styled([(name, None), ("  only in %s" % (
                    self.name_a if group == plans.ONLY_A else self.name_b,), 'grey')])
        return shown

    def _previews(self, send):
        """The previews: a differing file's versions and what each arrow does with them, a moved one's
        other path, and why the AI set an arrow"""
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
        for relpath, match in self.moved.items():
            lines_of[relpath] = [picker.styled([("↔ Moved", 'bold,' + plans.MOVE_COLOR)]),
                                 "The same contents are in %s at" % (self.name_b,), "  " + match, "",
                                 "→ moves %s's there to here" % (self.name_b,), "← moves this one there"]
        for relpath, reason in (self.ai_reasons or {}).items():
            lines_of[relpath] = lines_of.get(relpath, [os.path.basename(relpath)]) + [
                "", picker.styled([("Why (AI):", 'bold,magenta')]), "  " + (reason or "(it didn't say)")]
        send(lines_of, default=[])
