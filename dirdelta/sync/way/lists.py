"""What the sync's picker lists: the missing files, the ones that differ, and their previews"""
import os

from dirdelta.matching import differing
from dirdelta.matching import elsewhere
from dirdelta.sync import replica_ops
from dirdelta.ui import messages
from dirdelta.util import dryrun


class Lists(object):
    """The picker's files (InteractiveDirSync's)"""

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
            lines = ["No file at the same path in %s and %s differs." % (self._src.displayname(), self._dst.displayname())]
        else:
            lines = ["%s has all of %s's files." % (self._dst.displayname(), self._src.displayname())]
        messages.show("Nothing to do", lines, dryrun.label())

    def _listed(self):
        """The relpaths of the files to show: src's that dst lacks (see _missing()), and those that
        differ (see _differs(), kept in differs), each dir's together"""
        missing = [] if self._only_differing else self._missing()
        self.differs = self._differs()
        if not self.differs:
            return missing
        return sorted(set(missing) | set(self.differs), key=lambda relpath: relpath.split('/'))

    def _differs(self):
        """The files both have that differ, src's way (differing.find()), saying if they couldn't be
        compared (then there are none)"""
        try:
            if self._differs_future is not None:
                return self._differs_future.result()
            return differing.find(self._src, self._dst)
        except Exception as error:
            messages.show("Warning: couldn't compare the files both have",
                          ["So the ones that differ aren't shown: %s" % (error,)], dryrun.label(), 'red')
            return {}

    def _find_previews(self, missing, differs, send):
        """The pickers' previews: the files that differ's (differing.preview_lines()) at once, then
        where dst may have the missing ones (elsewhere.find_previews())"""
        if differs:
            can_replace = replica_ops.can_copy(self._src, self._dst)
            send({relpath: differing.preview_lines(change, self._dst.displayname(), can_replace)
                  for relpath, change in differs.items()})
        if not missing:
            send(default=[])
            return
        elsewhere.find_previews(missing, self._src, self.dst_index, send, checked=self.checked,
                                src_index=self.src_index)

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
