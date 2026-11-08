"""The selected file's diff in the combined tree's right column (CombinedSync's), below its preview:
a differing text file's, in the view Ctrl-T chose (diffview.py); a text file only one has, its
contents. Ctrl-W l scrolls it, Ctrl-P hides the column."""
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import diffview
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker


class DiffPane(object):
    """The diff (CombinedSync's): its view stays as Ctrl-T left it, from one tree shown to the next;
    _diff_relpath: the file the selection is on (its preview gets the diff), _wake: set to send the
    previews at once (see Showing._send_previews())"""
    diff_view = diffview.SIDE_BY_SIDE
    _diff_relpath = None

    def _follow(self, selection, send):
        """on_selection's: the selected file's preview gets its diff. Lets picker.PickerClosed go up,
        once the picker is gone."""
        while True:
            self._diff_relpath = selection.wait_next()
            self._wake.set()

    def _next_view(self):
        """Ctrl-T: the next view of the diff"""
        self.diff_view = (self.diff_view + 1) % diffview.NR_VIEWS
        self._wake.set()

    def _diff_lines(self, relpath):
        """The file's diff's lines (or its contents', if only one has it), after a blank one and their
        title, worked out once for each view"""
        group = self.grouped.get(relpath)
        if group not in (plans.DIFFER, plans.ONLY_A, plans.ONLY_B):
            return []
        key = (relpath, self.diff_view if group == plans.DIFFER else None, diffview.column_width())
        if key not in self._diffs:
            self._diffs[key] = self._work_out_diff(relpath, group, key[2])
        return self._diffs[key]

    def _work_out_diff(self, relpath, group, width):
        if group == plans.DIFFER:
            title = picker.styled([("Diff, %s" % (diffview.view_name(self.diff_view, self.name_a, self.name_b),), 'bold'),
                                   ("  (%s: next view)" % (diffview.KEY_NAME,), 'grey')])
            replicas = (self.replica_a, self.replica_b)
        else:
            replica = self.replica_a if group == plans.ONLY_A else self.replica_b
            title = picker.styled([("Its contents", 'bold')])
            replicas = (replica,)
        versions = []
        for replica in replicas:
            if not replica_ops.is_local(replica):
                return ["", title, "  Drive's version isn't here: Ctrl-O downloads it and shows it"]
            versions.append(diffview.read_lines(replica.local_path(relpath)))
        if None in versions:
            return ["", title, "  Not text, or bigger than 1 MB (Ctrl-O shows it, if it's text)"]
        if group != plans.DIFFER:
            return ["", title] + versions[0][:diffview.MAX_LINES]
        return ["", title] + diffview.lines_of(self.diff_view, versions[0], versions[1], self.name_a, self.name_b, width)
