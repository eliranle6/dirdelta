"""Names the user types for the files and dirs moved into the sorted tree"""
import os
import posixpath

from dirdelta.inbox.constants import DESCRIBED
from dirdelta.inbox.formatting import join_path
from dirdelta.ui import messages
from dirdelta.util import dryrun


class TypedNames(object):
    """Asking for a moved file's or dir's name (InboxSort's)"""

    def _typed_name(self, plan):
        """plan (one file: [(relpath, its path in the sorted tree)]) with the name the user types for
        it there, starting as Claude's (or its own); None if they typed none, or one that can't be"""
        (relpath, target), = plan
        recommendation = self._claude.recommendation(relpath)
        default = os.path.basename(self._target(relpath) if recommendation and self._target(relpath)
                                   else relpath)
        lines = ["Moving %s" % (posixpath.join(self.inbox_path, relpath),),
                 "to %s/" % (join_path(self.root_path, os.path.dirname(target)),)]
        if self._claude.description(relpath) is not None:
            lines.append(DESCRIBED % (self._claude.description(relpath),))
        lines += ["", "Its name there (Enter to keep it as it is; an empty one, or Ctrl-C, to go back):"]
        name = messages.ask("The file's name in %s" % (self.root_path,), lines, "> ", default, dryrun.label())
        if name is None:
            return None
        if '/' in name or name in ('.', '..'):
            messages.show("Not a name", ["%r can't be a file's name: it's a name, without '/'." % (name,)],
                          dryrun.label(), 'red')
            return None
        return [(relpath, join_path(os.path.dirname(target), name))]

    def _typed_dir_name(self, dirpath, destination):
        """The name the user types for the inbox's dir at dirpath in the sorted tree's dir at
        destination, starting as its own; None if they typed none, or one that can't be"""
        lines = ["Moving %s/" % (posixpath.join(self.inbox_path, dirpath),),
                 "into %s/" % (join_path(self.root_path, destination),),
                 "", "Its name there (Enter to keep it as it is; an empty one, or Ctrl-C, to go back):"]
        name = messages.ask("The dir's name in %s" % (self.root_path,), lines, "> ", posixpath.basename(dirpath),
                            dryrun.label())
        if name is None:
            return None
        if '/' in name or name in ('.', '..'):
            messages.show("Not a name", ["%r can't be a dir's name: it's a name, without '/'." % (name,)],
                          dryrun.label(), 'red')
            return None
        return name
