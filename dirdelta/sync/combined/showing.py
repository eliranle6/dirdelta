"""What the combined tree shows: its header, tabs and footer, each file's tag (and the AI's), and the
previews, sent again as they change (CombinedSync's)"""
import collections
import os

from dirdelta.matching import differing
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker

# How often the previews are looked at again, to send what changed (as the sort's)
PREVIEWS_INTERVAL = 0.3
# (In steps, between which it looks whether the picker is gone)
STEPS = 6


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

    def _base_parts(self, relpath):
        """[(text, style)] of the file's name, and where it is: only in one, or in both, differing (its
        tag); worked out once"""
        if self._shown is None:
            self._shown = {}
        if relpath not in self._shown:
            name, group = os.path.basename(relpath), self.grouped[relpath]
            if group == plans.DIFFER:
                parts = [(name + differing.styled_tag(self.changes[relpath], (self.name_a, self.name_b)), None)]
            elif group == plans.MOVED:
                parts = [(name, None), ("  moved: in %s at %s" % (self.name_b, self.moved[relpath]), plans.MOVE_COLOR)]
            else:
                parts = [(name, None), ("  only in %s" % (self.name_a if group == plans.ONLY_A else self.name_b,), 'grey')]
            self._shown[relpath] = parts
        return self._shown[relpath]

    def _shown_as(self):
        """Each file as it's shown, as it changes: its name and where it is, and what the AI suggests
        (or that it's being asked); in the state it's put in (Ctrl-A); and the status of the AI's work"""
        shown = {}
        for relpath in self.grouped:
            tag = self._ai_tag(relpath)
            text = picker.styled(self._base_parts(relpath) + ([("  ", None), tag] if tag else []))
            applied = self._applied.get(relpath)
            shown[relpath] = picker.Stated(text, *applied) if applied else text
        shown[''] = self._ai_status()
        return shown

    def _send_previews(self, send):
        """Send the files' and dirs' previews, and again as they change (the AI's suggestions coming
        in, the selection moving to a differing file, whose diff is shown), until the picker is gone"""
        sent, seen = {}, None
        # (Woken by what changes, or the picker gone: its closing doesn't wait out the interval)
        pause = getattr(send, 'pause', None)
        while True:
            now = (self.suggestions.generation, self._diff_relpath, self.diff_view)
            if now != seen:
                seen = now
                previews = {relpath: self._file_preview(relpath) for relpath in self.grouped}
                if self._diff_relpath in previews:
                    previews[self._diff_relpath] = previews[self._diff_relpath] + self._diff_lines(self._diff_relpath)
                previews.update(self._dir_previews())
                changed = {relpath: lines for relpath, lines in previews.items() if sent.get(relpath) != lines}
                send(changed)
                sent.update(changed)
            else:
                # Sent even with nothing to send: it raises PickerClosed once the picker is gone
                send({})
            for _ in range(STEPS):
                if self._wake.wait(PREVIEWS_INTERVAL / STEPS):
                    break
                if pause is not None:
                    pause(0)
            self._wake.clear()

    def _dir_previews(self):
        """{dirpath: its preview} of every dir ('' the root), worked out in one pass over the files"""
        under = collections.defaultdict(list)
        for relpath in self.grouped:
            dirpath = os.path.dirname(relpath)
            while True:
                under[dirpath].append(relpath)
                if not dirpath:
                    break
                dirpath = os.path.dirname(dirpath)
        return {dirpath: self._dir_lines(dirpath, relpaths) for dirpath, relpaths in under.items()}

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
