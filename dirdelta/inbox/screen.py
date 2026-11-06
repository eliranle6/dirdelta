"""The inbox's picker: the loop that shows it and does what's chosen"""
import functools

from dirdelta.inbox.constants import DESCRIBE_KEY, LABEL, OPEN_KEY
from dirdelta.inbox.formatting import is_at_or_under
from dirdelta.known import mounts
from dirdelta.known import replicanames
from dirdelta.matching import elsewhere
from dirdelta.matching import junk
from dirdelta.screens import aiplan_screen
from dirdelta.screens import archive_screen
from dirdelta.screens import hashes_screen
from dirdelta.ui import contextmenu
from dirdelta.ui import filescreen
from dirdelta.ui import images
from dirdelta.ui import messages
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.ui import renaming
from dirdelta.util import dryrun
from dirdelta.sync import replica_ops


class Screen(object):
    """The inbox's picker, shown until it's quit (InboxSort's)"""

    # The screens

    def _cant_be_done(self):
        """The actions of the kinds that a read-only inbox (what takes files out of it, or moves them in
        it) or sorted tree (what puts files in it) can't have done"""
        cant = set()
        if not replica_ops.is_writable(self._inbox_tree):
            cant |= {self.MOVE_TO, self.MOVE_RECOMMENDED, self.MOVE_TO_CLAUDES_DIR, self.MOVE_TO_CLAUDES_DIR_TYPED,
                     self.MOVE_TO_CLAUDES_NAMES, self.MOVE_TO_TYPED, self.MOVE_IN_INBOX,
                     self.MOVE_DIR, self.MOVE_DIR_TO, self.MOVE_DIR_TO_TYPED,
                     self.REMOVE, self.REMOVE_COPIES, self.REMOVE_JUNK, self.REMOVE_DIR}
        if not replica_ops.is_writable(self._root_tree):
            cant |= {self.MOVE_TO, self.MOVE_RECOMMENDED, self.MOVE_TO_CLAUDES_DIR, self.MOVE_TO_CLAUDES_DIR_TYPED,
                     self.MOVE_TO_CLAUDES_NAMES, self.MOVE_TO_TYPED, self.COPY_TO,
                     self.MOVE_DIR, self.MOVE_DIR_TO, self.MOVE_DIR_TO_TYPED}
        return cant

    def _warn_if_read_only(self):
        """Say what can't be done if the inbox or the sorted tree is read-only, and what still can"""
        lines = []
        if not replica_ops.is_writable(self._inbox_tree):
            lines.append("%s is read-only: you can still copy its files to the sorted tree, but they can't be "
                         "moved out of it or removed." % (self.inbox_path,))
            lines += mounts.read_only_lines_of(self.inbox_path)
        if not replica_ops.is_writable(self._root_tree):
            lines.append("%s is read-only: no files can go into it." % (self.root_path,))
            lines += mounts.read_only_lines_of(self.root_path)
        if lines:
            messages.show("Read-only", lines, dryrun.label(), 'yellow')

    def run(self):
        """Let the user pick some of the inbox's files, then choose what to do with them (_act()),
        and back to the picker, where they were, until they quit, or the inbox is empty"""
        self._warn_if_read_only()
        header = ("Files in %s, to sort into %s. Pick some, then choose what to do with them." %
                  (replicanames.full(self.inbox_path), replicanames.full(self.root_path)))
        keys = self.REFRESH_KEY + hashes_screen.KEY + aiplan_screen.KEY + contextmenu.KEY + archive_screen.KEY
        # The keys row has little room: the rest are in the menu (:), and ?
        key_hints = [('Enter', 'choose what to do'), contextmenu.KEY_HINT]
        more_keys = ([aiplan_screen.KEY_HINT, archive_screen.KEY_HINT, ('Ctrl-I', 'Claude: describe, and say where they go (a dir: as a whole)'),
                      opening.KEY_HINT, renaming.KEY_HINT,
                      ('Ctrl-W l', 'move to the sorted tree, on the right (Ctrl-W h: back)')] +
                     [(self.REFRESH_KEY_NAME, 'read the folder anew from Drive' if self.inbox_is_cloud else 'see what changed outside dirdelta'),
                      hashes_screen.KEY_HINT])
        help_lines = (picker.key_help_lines(more_keys) + ["Tags after a file's name (/ searches them too):",
                       "  [claude: ...]            what Claude says it is",
                       "  [junk? ...]              it may be removed (by its name or size, or as Claude says)"] +
                      (hashes_screen.HELP_LINES[1:] if self._jobs() else []))
        picked, selected = [], None
        # Where to go on in the sorted tree, after Ctrl-R there
        side_start = None
        is_first = True
        shown_before = []
        while True:
            files = self._inbox_files()
            # It may be gone, whatever was done (it's also listed anew for changes outside dirdelta)
            if selected is not None:
                selected = filescreen.shown_near(selected, files, shown_before)
            shown_before = files
            if is_first:
                self._side_items()
                self._warn_if_not_all_read()
                is_first = False
            if not files:
                messages.show("The inbox is empty", ["%s has no files to sort." % (self.inbox_path,)],
                              dryrun.label())
                return
            self._load_cached(files)
            self._junk_by_name = junk.find(files, {relpath: self._listed(relpath)[0] for relpath in files})
            self._start_indexing()
            chosen = picker.pick_files(
                self.inbox_path, files, header=header, picked=picked, label=LABEL,
                keys=keys, selected=selected, key_hints=key_hints, help_lines=help_lines,
                previews=lambda send, files=files: self._send_previews(files, send),
                shown_as=lambda files=files: self._shown_as(files),
                notify_keys=DESCRIBE_KEY + OPEN_KEY, enter_picks_selection=True, twice_keys=renaming.KEY,
                side=picker.Side(self.root_path, self._side_items(), True, self._side_follow, self.REFRESH_KEY,
                                 [('Enter', ('copy' if self.MOVE_TO in self._cant_be_done() else 'move') + ' the files here'),
                                  (self.REFRESH_KEY_NAME, filescreen.SIDE_REFRESH_HINTS[self.root_is_cloud])],
                                 side_start),
                none_picked_key_hints=[('Enter', 'Pick & choose what to do')],
                on_notify=lambda key, selected, picked, files=files: self._on_key(key, selected, picked, files),
                on_selection=functools.partial(elsewhere.check_contents, files, self._inbox_tree,
                                               self._inbox_index, self._root_index, self._checked,
                                               sends_previews=False),
                images=images.of_replica(self._inbox_tree))
            if chosen is None:
                self._finish_describing()
                return
            selected = chosen.selected
            # After moving files, the next ones to pick are in the inbox's tree
            side_start = (chosen.side_selected if chosen.key == picker.SIDE_KEY and
                          chosen.side_pressed == self.REFRESH_KEY else None)
            chosen, left_picked = self._shared_key(chosen, files)
            if chosen is None:
                picked = left_picked
                continue
            if chosen.key == renaming.PRESSED:
                moved = self._rename_selected(selected)
                picked = [moved.get(relpath, relpath) for relpath in chosen.files]
                selected = moved.get(selected, selected)
                continue
            if chosen.key == self.REFRESH_KEY:
                self._read_inbox_anew(selected)
                picked = chosen.files
                continue
            if chosen.key == picker.SIDE_KEY and chosen.side_pressed == self.REFRESH_KEY:
                self._read_side_anew(chosen.side_selected)
                picked = chosen.files
                continue
            if chosen.key == picker.SIDE_KEY:
                # Enter in the sorted tree beside it: the picked files (or the selected one's) go there
                done = self._move_to_side([relpath for relpath in chosen.files] or
                                          [relpath for relpath in files if is_at_or_under(relpath, selected)],
                                          chosen.side_selected)
            elif chosen.key == aiplan_screen.KEY:
                # About the picked ones, or with none picked, all of them: the AI picks (and it's told
                # where the selection is)
                done = self._ask_ai(chosen.files or files,
                                    chosen.files or (contextmenu.under(files, selected) if selected else []))
            else:
                done = self._act(chosen.files, selected)
            if done is filescreen.READ_ANEW:
                self._read_inbox_anew(selected)
                picked = chosen.files
                continue
            if done is None:
                picked = chosen.files
                continue
            done = set(done)
            # Files moved into a local sorted tree (or out of a local inbox) are hashed there too
            for job in self._jobs():
                job.scan_in_background()
            picked = [relpath for relpath in chosen.files if relpath not in done]
