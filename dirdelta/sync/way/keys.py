"""What the sync picker's own keys do: its menus, the tree beside it, exploring and renaming"""
import os

from dirdelta.drive import clouddirtree
from dirdelta.screens import aiplan_screen
from dirdelta.screens import archive_screen
from dirdelta.screens import hashes_screen
from dirdelta.sync import replica_ops
from dirdelta.trees import entries
from dirdelta.trees import paths
from dirdelta.ui import contextmenu
from dirdelta.ui import messages
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.ui import renaming
from dirdelta.util import archives
from dirdelta.util import dryrun


class Keys(object):
    """The picker's keys (InteractiveDirSync's)"""

    def _dashboard(self):
        hashes_screen.dashboard([self._src, self._dst])

    def _menu_key(self, answer, selected, files):
        if answer == opening.KEY:
            self._opener.press([selected], set(files))
            return True
        return False

    def _context_menu(self, selected, missing):
        """What to do with nothing picked, on the picker's selected relpath (see contextmenu.py): what
        its keys do, as the key's returned, a contextmenu.PICK or WHAT_TO_DO, or None"""
        name = contextmenu.selected_name(selected)
        is_file = selected in set(missing)
        clouds = [replica for replica in (self._src, self._dst) if isinstance(replica, clouddirtree.CloudDirTree)]
        entries = [contextmenu.Entry(None, "Choose what to do with %s" % (name,), contextmenu.WHAT_TO_DO),
                   contextmenu.Entry('Space', "Pick %s" % (name,), contextmenu.PICK),
                   contextmenu.Entry(aiplan_screen.KEY_NAME, "Ask AI what to do with all the files, and review its plan",
                                     aiplan_screen.KEY)]
        if is_file and archives.is_archive(selected):
            entries.append(contextmenu.Entry(archive_screen.KEY_NAME, "Explore %s" % (name,), archive_screen.KEY))
        if is_file:
            entries.append(contextmenu.Entry(opening.KEY_HINT[0], "Open %s with its program" % (name,), opening.KEY))
        if selected:
            entries.append(contextmenu.Entry(renaming.KEY_HINT[0], "Rename %s" % (name,), renaming.PRESSED))
        if clouds:
            entries.append(contextmenu.Entry(self.REFRESH_KEY_NAME, "Read %s/ anew from Google Drive" % (
                os.path.dirname(selected) if is_file else selected or '.',), self.REFRESH_KEY))
        entries.append(contextmenu.Entry(hashes_screen.KEY, "Replicas dashboard", hashes_screen.KEY))
        return contextmenu.choose(entries, contextmenu.nothing_picked(len(missing)), side=self._dst.displayname())

    def _act_in_dst(self, relpath, is_removed=False):
        """Enter (or :) in the tree beside the picker, dst's, on the file or dir at relpath: choose what
        to do with it there, e.g. to remove a version of a repository that src has another of, then
        copy that one; with is_removed (d there), it's to remove it. Returns the files done (none in a dry run), or None if none were: then dst is diffed anew,
        as its files changed."""
        name = self._dst.displayname()
        if not relpath:
            messages.show("That's all of %s" % (name,), ["Select a file or dir in it."], dryrun.label())
            return None
        if not self.dst_index.is_built():
            messages.print_line("Looking through %s..." % (name,))
        self.dst_index.build()
        files = [path for path in sorted(contextmenu.under(self.dst_index.relpaths(), relpath))
                 if not paths.is_meta(path)]
        if not files:
            messages.show("Nothing to remove", ["%s has no files." % (relpath,)], dryrun.label())
            return None
        remove = "Remove %s (%s) from %s" % (relpath, replica_ops.files_text(len(files)), name)
        shown = {} if replica_ops.is_writable(self._dst) else {remove: picker.Disabled("%s: can't, it's read-only" % (remove,))}
        if is_removed and shown:
            messages.show("Can't remove it", ["%s is read-only." % (name,)], dryrun.label())
            return None
        answer = remove if is_removed else picker.pick_option(
            [self.NOTHING, remove], header="%s, in %s: what to do with it?" % (relpath, name),
            shown_as=lambda: shown, title="What to do")
        if answer != remove or not self._confirm(self.REMOVE, files, replica=self._dst):
            return None
        title = "Removing %s from %s%s" % (replica_ops.files_text(len(files)), name, " (a dry run)" if dryrun.DRYRUN else "")
        with messages.progress_screen(title, dryrun.label()):
            self._dst.remove_files([entries.FileEntry(os.path.basename(path), path,
                                                      os.path.join(self._dst.fullpath(), path)) for path in files])
        if dryrun.DRYRUN:
            return []
        done = [path for path in files if not self._dst.has_file(path)]
        # What src's files were compared with may be gone
        self.checked.clear()
        self._note(self._dst, 'removed', len(done))
        return done

    def _explore(self, relpath, files):
        """e: look in src's zip at relpath (see archive_screen.py)"""
        archive_screen.explore(relpath, files, lambda: self._opener.local_path(relpath))

    def _rename_selected(self, selected):
        """cc: rename src's file or dir at selected (see renaming.py). Returns (its new relpath, the
        files' moves), once it's renamed (then src is diffed anew), or None (as in a dry run)."""
        renamed = renaming.rename(self._src, selected)
        if renamed is None or dryrun.DRYRUN:
            return None
        new_relpath, moves = renamed
        for relpath, new in moves:
            # Compared under its old path
            self.checked.pop(relpath, None)
        self._note(self._src, 'moved', len(moves))
        self.has_changed = True
        self._missing_future = None
        # Its hashes are kept under the new paths: the job lists them there
        for job in hashes_screen.jobs_of([self._src]):
            job.scan_in_background()
        return new_relpath, moves
