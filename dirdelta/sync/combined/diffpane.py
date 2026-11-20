"""The selected file's diff in the combined tree's right column (CombinedSync's), below its preview:
a differing text file's, in the view Ctrl-T chose (versions.py, diffview.py: a Drive version downloaded for it); a text file only one has, its
contents. Ctrl-W l scrolls it, Ctrl-P hides the column."""
from dirdelta.sync.combined import plan as plans
from dirdelta.sync.combined import versions


class DiffPane(object):
    """The diff (CombinedSync's): its view stays as Ctrl-T left it, from one tree shown to the next (None:
    the first, see versions.views()); _diff_relpath: the file the selection is on (its preview gets the
    diff), _wake: set to send the previews at once (see Showing._send_previews())"""
    diff_view = None
    _diff_relpath = None

    def _follow(self, selection, send):
        """on_selection's: the selected file's preview gets its diff. Lets picker.PickerClosed go up,
        once the picker is gone."""
        while True:
            self._diff_relpath = selection.wait_next()
            self._wake.set()

    def _next_view(self):
        """Ctrl-T: the next view of the diff"""
        self.diff_view = versions.next_view(self.diff_view)
        self._wake.set()

    def _diff_lines(self, relpath):
        """The file's diff's lines (or its contents', if only one has it), after a blank one and their
        title, worked out once for each view (a Drive version downloaded for it)"""
        group = self.grouped.get(relpath)
        if group not in (plans.DIFFER, plans.ONLY_A, plans.ONLY_B):
            return []
        key = (relpath, self.diff_view if group == plans.DIFFER else None, versions.width())
        if key not in self._diffs:
            if group == plans.DIFFER:
                replicas, names = (self.replica_a, self.replica_b), (self.name_a, self.name_b)
            else:
                replicas = (self.replica_a if group == plans.ONLY_A else self.replica_b,)
                names = ()
            self._diffs[key] = versions.lines(replicas, relpath, names, self.diff_view)
        return self._diffs[key]
