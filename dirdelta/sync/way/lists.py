"""What the sync's picker lists: the missing files, the ones that differ, and their previews"""
import os

from dirdelta.known import replicanames
from dirdelta.matching import differing
from dirdelta.matching import elsewhere
from dirdelta.sync import comparing
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import versions
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


class Lists(object):
    """The picker's files (InteractiveDirSync's). _diff_view: the view of a file that differs' diff, as
    Ctrl-T left it (None: the first, see versions.views()); _diff_at: (the file that differs selected, the
    send() its diff went by)"""
    _diff_view = None
    _diff_at = None

    def _send_diff(self, relpath, send):
        """A file that differs, selected (check_contents()'s on_other): its preview again, with its diff
        below (in the view Ctrl-T chose, a Drive version downloaded for it)"""
        change = self.differs.get(relpath)
        if change is None:
            return
        self._diff_at = (relpath, send)
        shown = differing.preview_lines(change, self._dst.screen_name(), replica_ops.can_copy(self._src, self._dst))
        if not (replica_ops.is_local(self._src) and replica_ops.is_local(self._dst)):
            send({relpath: shown + ["", picker.styled([("Getting its versions for their diff...", 'grey')])]})
        names = replicanames.short_names([self._path_of(self._src), self._path_of(self._dst)])
        send({relpath: shown + versions.lines((self._src, self._dst), relpath,
                                              (names[self._path_of(self._src)], names[self._path_of(self._dst)]), self._diff_view)})

    @staticmethod
    def _path_of(replica):
        """The replica's path, as the replicas' names know it (a Drive one's: cloud/...)"""
        return replica.fullpath() if replica_ops.is_local(replica) else replica.displayname()

    def _next_diff_view(self, selected):
        """Ctrl-T: the diff's next view, and the selected file's sent again in it"""
        self._diff_view = versions.next_view(self._diff_view)
        if self._diff_at is not None and self._diff_at[0] == selected:
            self._send_diff(*self._diff_at)

    def _side_items(self):
        """dst's dirs and files, for the tree beside the picker (see sidetree.py)"""
        return self._side_listing.items()

    def _side_follow(self, relpath):
        """Where in dst src's file at relpath is related to, for the tree beside the picker: its
        other version, if it's one that differs; else a file of its name there (the first, by path),
        or else its own path (the closest dir dst has)"""
        if relpath in self.differs:
            return relpath
        if self.dst_index.is_built():
            named = self.dst_index.files_named(os.path.basename(relpath))
            if named:
                return sorted(named)[0]
        return relpath

    def _index_of(self, replica):
        return self.src_index if replica is self._src else self.dst_index

    def _say_nothing(self):
        if self._only_differing:
            lines = ["No file at the same path in %s and %s differs." % (self._src.screen_name(), self._dst.screen_name())]
        else:
            lines = ["%s has all of %s's files." % (self._dst.screen_name(), self._src.screen_name())]
        unverified = comparing.unverified_line(self.differs)
        if unverified:
            lines += ["", picker.unstyled(unverified)]
        messages.show("Nothing to do", lines, dryrun.label())

    def _listed(self):
        """The relpaths of the files to show: src's that dst lacks (see _missing()), and those that
        differ (see _differs(), kept in differs), each dir's together"""
        missing = [] if self._only_differing else self._missing()
        self.differs = self._differs()
        if not self.differs or not self._with_differing:
            return missing
        return sorted(set(missing) | set(self.differs), key=lambda relpath: relpath.split('/'))

    def _differs(self):
        """The files both have that differ, src's way (differing.find()), saying if they couldn't be
        compared (then there are none)"""
        try:
            if self._differs_future is not None:
                return self._differs_future.result()
            return differing.find(self._src, self._dst, self._compared)
        except Exception as error:
            messages.show("Warning: couldn't compare the files both have",
                          ["So the ones that differ aren't shown: %s" % (error,)], dryrun.label(), 'red')
            return {}

    def _find_previews(self, missing, differs, send):
        """The pickers' previews: the files that differ's (differing.preview_lines()) at once, then
        where dst may have the missing ones (elsewhere.find_previews())"""
        if differs:
            can_replace = replica_ops.can_copy(self._src, self._dst)
            send({relpath: differing.preview_lines(change, self._dst.screen_name(), can_replace)
                  for relpath, change in differs.items()})
        if not missing:
            send(default=[])
            return
        elsewhere.find_previews(missing, self._src, self.dst_index, send, checked=self.checked,
                                src_index=self.src_index, on_status=self._set_finding)

    def _set_finding(self, text):
        """How far finding where dst has the files got (None: done), for the status bar (see picking.py)"""
        self.finding = text

    def _missing(self):
        """The relpaths of src's files that dst lacks (see replica_ops.find_missing()), warning if scanning
        couldn't read everything"""
        if self._missing_future is not None:
            missing = self._missing_future.result()
        else:
            missing = replica_ops.find_missing(self._src, self._dst)
        if missing.warning:
            messages.show("Warning: couldn't read everything", missing.warning, dryrun.label(),
                          'red')
        return missing.relpaths
