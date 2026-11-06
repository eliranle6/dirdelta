"""Choosing a dir of the sorted tree (or the inbox) for files to go to"""
import posixpath

from dirdelta.drive import clouddirtree
from dirdelta.inbox.constants import LABEL
from dirdelta.inbox.formatting import is_at_or_under, join_path, relpath_in
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.ui import renaming
from dirdelta.util import dryrun


class Dirs(object):
    """Choosing dirs (InboxSort's)"""

    # Moving, copying, removing

    def _choose_dir(self, verb, count):
        """Let the user choose the dir in the sorted tree to move or copy (verb) the files (count, e.g.
        '2 files') to: one of its recent ones, if it has any, or one picked (_pick_dir()). Returns its
        relpath ('' the root), or None."""
        recent = self._known_replicas.dirs_of(self.root_path) if self._known_replicas is not None else []
        if not recent:
            return self._pick_dir(verb, count)
        options = {self.RECENT_DIR % (relpath or '.',): relpath for relpath in recent}
        pick = self.PICK_DIR
        # Picking one first, then the recent ones, apart
        answer = picker.pick_option(picker.grouped([[pick], list(options)]), header="Where in %s to %s the %s?" %
                                    (self.root_path, verb, count), label=LABEL, title="Where to")
        if answer == pick:
            return self._pick_dir(verb, count)
        if answer not in options:
            return None
        return self._not_the_inbox(options[answer])

    def _pick_dir(self, verb, count, in_inbox=False):
        """Let the user pick a dir in the sorted tree (with in_inbox, in the inbox) to move or copy
        (verb) the files (count) to, or make a new one: in the selected one (NEW_DIR_KEY), or beside
        it (o or O, as vim's), then its name; cc renames the selected one. Returns its relpath (''
        the root), or None."""
        base, is_cloud = (self.inbox_path, self.inbox_is_cloud) if in_inbox else (self.root_path, self.root_is_cloud)
        header = "Pick the dir in %s to %s the %s to." % (base, verb, count)
        keys = self.NEW_DIR_KEY + self.SIBLING_DIR_KEYS
        # Not what can't be picked (typed, it's still refused: see _not_the_inbox())
        excluded = [paths.META_DIR] + ([self._inbox_in_root] if not in_inbox and self._inbox_in_root else [])
        key_hints = [('Enter', 'this dir'), (self.NEW_DIR_KEY, 'a new dir in it'), ('o/O', 'a new dir beside it'),
                     renaming.KEY_HINT]
        while True:
            if is_cloud:
                root = clouddirtree.factory(base)
                picked = picker.pick_from_tree(root, header=header, dirs_only=True, root_name=base,
                                               keys=keys, key_hints=key_hints, twice_keys=renaming.KEY, excluded=excluded)
                key, relpath = (picked[0], picked[1][0].relpath) if picked else ('', None)
            else:
                picked = picker.pick_under_dir(base, dirs_only=True, lazy=True, header=header,
                                               keys=keys, key_hints=key_hints, twice_keys=renaming.KEY, excluded=excluded)
                key, relpath = (picked[0], relpath_in(picked[1], base)) if picked else ('', None)
            if relpath is None or key != renaming.PRESSED:
                break
            if in_inbox:
                self._rename_selected(relpath)
            else:
                self._rename_sorted_dir(relpath)
        if relpath is not None and key == self.NEW_DIR_KEY:
            relpath = self._new_dir(relpath, verb, count, base)
        elif relpath is not None and key and key in self.SIBLING_DIR_KEYS:
            # Beside it: in its dir (beside the root, there's none: in it)
            relpath = self._new_dir(posixpath.dirname(relpath), verb, count, base)
        return self._not_dirdeltas(relpath) if in_inbox else self._not_the_inbox(relpath)

    def _rename_sorted_dir(self, relpath):
        """cc in the dir picker: rename the sorted tree's dir at relpath (see renaming.py), but the
        inbox's, or one it's in"""
        if self._inbox_in_root is not None and is_at_or_under(self._inbox_in_root, relpath):
            messages.show("Can't rename it", ["The inbox is in %s/: rename another dir." % (join_path(self.root_path, relpath),)],
                          dryrun.label())
            return
        with self._drive_lock:
            renamed = renaming.rename(self._root_tree, relpath, LABEL)
        if renamed is None or dryrun.DRYRUN:
            return
        _, moves = renamed
        # (An empty dir's rename tells nothing)
        self._side_listing.invalidate()
        self.changes.note(self.root_path, 'moved', len(moves))

    def _new_dir(self, parent, verb, count, base=None):
        """The relpath of a new dir in the sorted tree's (or base's, the inbox's) dir at parent, its
        name typed (a/b: one in a new one), to move or copy (verb) the files (count) to; it's made
        when they go there. None if no name, or one that can't be, was typed."""
        base = base or self.root_path
        name = messages.ask("A new dir in %s/" % (join_path(base, parent),),
                            ["The new dir to %s the %s to, in %s/" % (verb, count, join_path(base, parent)),
                             "(a/b makes b in a new a). An empty name, or Ctrl-C, goes back."],
                            "> ", label=dryrun.label())
        if name is None:
            return None
        parts = name.strip('/').split('/')
        if any(part in ('', '.', '..') for part in parts):
            messages.show("Not a dir's name", ["%r can't be a new dir's name." % (name,)], dryrun.label(), 'red')
            return None
        return join_path(parent, *parts)

    def _not_dirdeltas(self, relpath):
        """relpath (a dir in the inbox or the sorted tree), unless it's where dirdelta keeps its own
        files, or in it (then it says so, and it's None)"""
        if relpath is not None and paths.is_meta(relpath):
            messages.show("That's dirdelta's", ["%s/ has dirdelta's own files: pick another dir." % (paths.META_DIR,)],
                          dryrun.label())
            return None
        return relpath

    def _not_the_inbox(self, relpath):
        """relpath (a dir in the sorted tree), unless it's the inbox or in it, or dirdelta's own (then
        it says so, and it's None)"""
        relpath = self._not_dirdeltas(relpath)
        if relpath is not None and self._is_in_inbox(relpath):
            messages.show("That's the inbox", ["Pick a dir of %s that isn't in the inbox." % (self.root_path,)],
                          dryrun.label())
            return None
        return relpath
