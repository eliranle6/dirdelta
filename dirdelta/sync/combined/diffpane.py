"""The selected differing file's diff in the combined tree's right column (CombinedSync's), below its
preview, in the view v chose (diffview.py); Ctrl-W l scrolls it, Ctrl-P hides the column"""
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import diffview
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker


class DiffPane(object):
    """The diff (CombinedSync's): its view stays as v left it, from one tree shown to the next"""
    diff_view = diffview.SIDE_BY_SIDE
    _send = None

    def _follow(self, selection, send):
        """on_selection's: the selected file's preview, with its diff if it differs. Lets
        picker.PickerClosed go up, once the picker is gone."""
        self._send = send
        while True:
            self._send_diff(selection.wait_next())

    def _on_notify(self, key, selected):
        """v: the next view of the selected file's diff"""
        if key == diffview.KEY:
            self.diff_view = (self.diff_view + 1) % diffview.NR_VIEWS
            try:
                self._send_diff(selected)
            except picker.PickerClosed:
                pass

    def _send_diff(self, relpath):
        if self._send is not None and self.grouped.get(relpath) == plans.DIFFER:
            self._send({relpath: self._file_preview(relpath) + self._diff_lines(relpath)})

    def _diff_lines(self, relpath):
        """The diff's lines, after a blank one and its title (the view, and the keys)"""
        title = picker.styled([("Diff, %s" % (diffview.view_name(self.diff_view, self.name_a, self.name_b),), 'bold'),
                               ("  (v: next view)", 'grey')])
        versions = []
        for replica in (self.replica_a, self.replica_b):
            if not replica_ops.is_local(replica):
                return ["", title, "  Drive's version isn't here: d downloads it and shows the diff"]
            versions.append(diffview.read_lines(replica.local_path(relpath)))
        if None in versions:
            return ["", title, "  Not text (or bigger than 1 MB: d shows the diff, if it's text)"]
        return ["", title] + diffview.lines_of(self.diff_view, versions[0], versions[1], self.name_a, self.name_b,
                                               diffview.column_width())
