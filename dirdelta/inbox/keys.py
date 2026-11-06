"""What the inbox picker's own keys do: its menus, exploring, renaming and opening"""
import posixpath

from dirdelta.claude import ai
from dirdelta.inbox.constants import DESCRIBE_KEY, LABEL, OPEN_KEY
from dirdelta.inbox.formatting import is_at_or_under
from dirdelta.screens import aiplan_screen
from dirdelta.screens import archive_screen
from dirdelta.screens import hashes_screen
from dirdelta.ui import contextmenu
from dirdelta.ui import messages
from dirdelta.ui import opening
from dirdelta.ui import renaming
from dirdelta.util import archives
from dirdelta.util import downloads
from dirdelta.util import dryrun


class Keys(object):
    """The inbox picker's keys (InboxSort's)"""

    def _dashboard(self):
        hashes_screen.dashboard(self._trees(), self._known_replicas)

    def _menu_key(self, answer, selected, files):
        if answer in (OPEN_KEY, DESCRIBE_KEY):
            self._on_key(answer, selected, [], files)
            return True
        return False

    def _context_menu(self, selected, files):
        """What to do with nothing picked, on the picker's selected relpath (see contextmenu.py): what
        its keys do, as the key's returned, a contextmenu.PICK or WHAT_TO_DO, or None"""
        name = contextmenu.selected_name(selected)
        is_file = selected in set(files)
        entries = [contextmenu.Entry('Enter', "Choose what to do with %s" % (name,), contextmenu.WHAT_TO_DO),
                   contextmenu.Entry('Space', "Pick %s" % (name,), contextmenu.PICK),
                   contextmenu.Entry(aiplan_screen.KEY_NAME, "Ask AI what to do with all the files, and review its plan",
                                     aiplan_screen.KEY),
                   contextmenu.Entry('Ctrl-I', ("Have Claude say what %s is and where it goes, as a whole, while you go "
                                                "on (each of its files: pick them, then Ctrl-I)" % (name,))
                                     if selected and not is_file else
                                     "Have Claude describe %s and say where it goes, while you go on" % (name,),
                                     DESCRIBE_KEY)]
        if is_file and archives.is_archive(selected):
            entries.append(contextmenu.Entry(archive_screen.KEY_NAME, "Explore %s" % (name,), archive_screen.KEY))
        if is_file:
            entries.append(contextmenu.Entry(opening.KEY_HINT[0], "Open %s with its program" % (name,), OPEN_KEY))
        if selected:
            entries.append(contextmenu.Entry(renaming.KEY_HINT[0], "Rename %s" % (name,), renaming.PRESSED))
        if self.inbox_is_cloud:
            entries.append(contextmenu.Entry(self.REFRESH_KEY_NAME, "Read %s/ anew from Google Drive" % (
                posixpath.dirname(selected) if is_file else selected or '.',), self.REFRESH_KEY))
        entries.append(contextmenu.Entry(hashes_screen.KEY, "Replicas dashboard", hashes_screen.KEY))
        return contextmenu.choose(entries, contextmenu.nothing_picked(len(files)), LABEL, side=self.root_path)

    def _explore(self, relpath, files):
        """e: look in the inbox's zip at relpath (see archive_screen.py)"""
        archive_screen.explore(relpath, files, lambda: self._opener.local_path(relpath), LABEL)

    def _rename_selected(self, selected):
        """cc: rename the inbox's file or dir at selected (see renaming.py), what's known of its
        files going with them. Returns {relpath: new relpath} of it and its files (none, if it
        wasn't renamed, or in a dry run)."""
        if not selected:
            messages.show("Can't rename it", ["That's the inbox: rename a file or dir in it."], dryrun.label())
            return {}
        with self._drive_lock:
            renamed = renaming.rename(self._inbox_tree, selected, LABEL)
        if renamed is None or dryrun.DRYRUN:
            return {}
        new_full, moves = renamed
        moved = dict(moves)
        self._carry(moved)
        moved[selected] = new_full
        return moved

    def _carry(self, moved):
        """After the inbox's files moved within it (moved: {relpath: new relpath}), what's known of
        each goes with it: what Claude said (in its cache too), the contents compared, its hash"""
        with self._claude.lock:
            for relpath, new in moved.items():
                for known in self._claude.kept_of() + (self._checked, self._junk_by_name):
                    if relpath in known:
                        known[new] = known.pop(relpath)
        # What Claude said of each, in its cache, under its new path (the same size)
        sizes = {new: self._size(new) for new in moved.values()}
        ai.carry({self._path_key(relpath, sizes[new]): self._path_key(new, sizes[new]) for relpath, new in moved.items()})
        # Its hashes are kept under the new paths: the jobs list them there
        for job in self._jobs():
            job.scan_in_background()

    # Opening a file

    def _on_key(self, key, selected, picked, files):
        """A notify key pressed in the picker of files (on another thread): Ctrl-X opens the
        selected file (not the picked ones: the menu's Open does, see opening.confirm()), Ctrl-I asks Claude about the picked ones (or the selected one, or
        with none picked, the selected dir as a whole; the root's files each)"""
        if key == OPEN_KEY:
            # The selected one only (the picked ones: the menu's Open, which downloads them first)
            self._opener.press([selected], files)
        elif not picked and selected and selected not in set(files):
            # A dir: Claude says what it is and where it goes as a whole (Space picks its files, for each)
            self.ask_dir_in_background(selected, [relpath for relpath in files if is_at_or_under(relpath, selected)])
        else:
            self.ask_in_background(picked or [relpath for relpath in files if is_at_or_under(relpath, selected)],
                                   anew=True)

    def open_in_background(self, relpaths, files):
        """Open the inbox's files at relpaths (of files; the rest are dirs) with their programs, on
        a thread of its own (see opening.Opener). The bottom line says how it went."""
        return self._opener.open_in_background(relpaths, files)

    def _downloaded(self, relpath):
        """The local path of the inbox's Drive file at relpath, downloaded unless it was (see
        downloads.py). Raises OSError if it can't be."""
        return downloads.get(posixpath.join(self.inbox_path, relpath), self._size(relpath),
                             lambda local_path: self._inbox_tree.fetch_file(relpath, local_path))
