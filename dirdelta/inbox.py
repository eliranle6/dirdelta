"""Sorting an inbox: a dir of files not yet sorted (e.g. cloud/unsorted), whose files the user moves
into a sorted tree (e.g. cloud/eliran), copies there, or removes, with Claude's help if they ask
for it (ai.py): a short description of each file, shown after its name, and where in the sorted
tree it belongs, shown beside it, to move it there.

When the inbox and the sorted tree are both local dirs, or both in Drive, the files are moved within
one tree that has both (their common dir, or Drive's), so a move is a rename (in Drive, one request
that keeps the file's id). When one is local and the other in Drive, a move is a copy (an upload or
a download, as a sync's), then the file's removal from the inbox, once it's there."""
import collections
import contextlib
import functools
import os
import posixpath
import re
import shutil
import textwrap
import threading
import time

from dirdelta import ai
from dirdelta import aiplan
from dirdelta import aiplan_screen
from dirdelta import archive_screen
from dirdelta import archives
from dirdelta import clouddirtree
from dirdelta import contextmenu
from dirdelta import drivecache
from dirdelta import downloads
from dirdelta import drivemeta
from dirdelta import dryrun
from dirdelta import elsewhere
from dirdelta import entries
from dirdelta import filescreen
from dirdelta import hashcache
from dirdelta import hashes_screen
from dirdelta import hashing
from dirdelta import interactive_dir_sync
from dirdelta import junk
from dirdelta import localdiskdirtree
from dirdelta import localscan
from dirdelta import messages
from dirdelta import opening
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicalog
from dirdelta import replicanames
from dirdelta import renaming
from dirdelta import replicas
from dirdelta import sidetree
from dirdelta import text

# The label of the inbox's screens, so they're told from a sync's
LABEL = ('SORT', 'cyan')
# How wide the preview column's wrapped lines are, at most
PREVIEW_WIDTH = 40
# How often the picker's previews are looked at for changes (Claude's descriptions coming in), and
# how often Ask where they go looks whether the descriptions it waits for came, in seconds
PREVIEWS_INTERVAL = 0.3
DESCRIBED_WAIT_INTERVAL = 0.2
# The key that describes the picked files (or the selected one) with Claude, in the background
DESCRIBE_KEY = '\t'
# The key that opens the selected file (Ctrl-X) with its program (see opening.py)
OPEN_KEY = opening.KEY
# How many of a dir's file names Claude is given, so it sees how they're named
NAMES_PER_DIR = 3
# What says a file of the inbox is in the sorted tree already, in its preview: highlighted
SURELY_A_COPY = picker.highlighted("\u2192 a copy: it may be removed")
# What says a file looks like junk, in its preview: in yellow, since it's a guess, not a copy's sure
# green
MAYBE_JUNK = picker.highlighted("\u2192 junk? it may be removed", 'yellow')
# What a file that looks like junk is shown as, after its name (and its description): a search
# (/) for 'junk?' finds them all
JUNK_BY_NAME = "[junk? %s]"
JUNK_BY_CLAUDE = "[claude: junk? %s]"
# What a file being described is shown as, after its name
LOOKING = "(Claude is looking at it...)"
# What a file Claude described is shown as, after its name: a search (/) for 'claude:' finds them,
# and one for a word finds the files Claude said it of
DESCRIBED = "[claude: %s]"
# The style of what Claude says, after a file's name (see picker.styled()): in Claude's color, as
# its options' in the action menu (VERB_COLORS)
CLAUDE_STYLE = 'magenta'
# The titles of what Claude says, in the preview column
DESCRIPTION_TITLE = "Description (ai):"
DESTINATION_TITLE = "Dest. path recommendation (ai):"
# The title of whether the sorted tree has the file already (by its contents)
IN_SORTED_TREE_TITLE = "Is in replica dir:"


# What an option of the action menu does to the files, and its color: its text's, and its label's
# in the lines below the menu (Claude's in magenta, as what comes from Claude there)
ASK = 'claude'
MOVE = 'move'
COPY = 'copy'
REMOVE = 'remove'
OPEN = 'open'
READ = 'read'
VERB_COLORS = {ASK: 'magenta', MOVE: 'blue', COPY: 'cyan', REMOVE: 'red', OPEN: 'green', READ: 'yellow'}
# A part of a destination's path: where it comes from, and its bracket's color and names (the
# first that fits), e.g. [Claude's dir] (Claude's in magenta, as its options' color)
SORTED_TREE = ((None), ("sorted tree", "tree"))
THE_INBOX = (None, ("the inbox", "inbox"))
CLAUDES_DIR = ('magenta', ("Claude's dir", "Claude's", "Claude"))
CLAUDES_NAME = ('magenta', ("Claude's name", "Claude's", "Claude"))
YOUR_DIR = ('yellow', ("your pick", "yours"))
YOUR_NAME = ('yellow', ("you type it", "yours"))
OWN_NAME = ('green', ("its own name", "own name", "own"))


class InboxError(Exception):
    pass


_files = text.files


def _of(count, total):
    """How many of the picked files (total) count is: 'the 3 files' when it's all of them, else '3 of
    the 5 files'"""
    if count == total:
        return "the " + _files(count)
    return "%d of the %s" % (count, _files(total))


_join = paths.join


class _Action(object):
    """What the inbox's action menu may do with the picked files: its label; why it can't be done
    (None: it can); what it does (a verb, see VERB_COLORS) and where it puts them (parts, the path's,
    see _destination_lines()); run(), which does it, returning what _act() does; and for the lines
    below the menu, the files it's done to (else the picked ones), or what it says of itself (said:
    (a verb, words)) instead"""
    def __init__(self, label, why_not, verb, parts, run, acted_on=None, said=None):
        self.label = label
        self.why_not = why_not
        self.verb = verb
        self.parts = parts
        self.run = run
        self.acted_on = acted_on
        self.said = said


class InboxSort(filescreen.FilesScreen):
    """The inbox at inbox_path and the sorted tree at root_path (local dirs, or cloud paths)"""
    NOTHING = "Nothing: back to the files"
    # What the picker's keys do on the selected file, in the menu too: opening it (Ctrl-X), reading
    # its folder anew from Drive (r)
    OPEN = 'open'
    READ_ANEW = 'read anew'
    DESCRIBE = 'describe'
    RECOMMEND = 'recommend'
    ASK_AI = 'ask AI'
    EXPLORE = 'explore'
    # The picker's keys that do an option of the menu, shown before it
    # (Ctrl-X opens the selected one, not the picked ones: Open has no key)
    SHORTCUTS = {ASK_AI: aiplan_screen.KEY_NAME, EXPLORE: archive_screen.KEY_NAME, RECOMMEND: 'Ctrl-I', READ_ANEW: 'Ctrl-R'}
    # Moving: to Claude's dir, or to a dir the user picks; under the file's name, Claude's, or one
    # the user types
    MOVE_RECOMMENDED = 'move to the recommendations'
    MOVE_TO_CLAUDES_DIR = "move to Claude's dirs"
    MOVE_TO_CLAUDES_DIR_TYPED = "move to Claude's dir, typing its name"
    MOVE_TO = 'move to'
    MOVE_TO_CLAUDES_NAMES = "move to, under Claude's names"
    MOVE_TO_TYPED = 'move to, typing its name'
    # To another dir of the inbox
    MOVE_IN_INBOX = 'move in the inbox'
    COPY_TO = 'copy to'
    REMOVE = 'remove'
    REMOVE_COPIES = 'remove the copies'
    REMOVE_JUNK = 'remove the junk'
    # The dir picker's key that makes a new dir in the selected one (its name typed next)
    NEW_DIR_KEY = 'n'
    # The dir picker's keys that make a new dir beside the selected one, as vim's o and O (a dir
    # on disk has no order: both are in its dir)
    SIBLING_DIR_KEYS = 'oO'
    # Where files go: a dir picked in the sorted tree, or one of the recent ones (by its relpath in
    # it: the header names the sorted tree)
    PICK_DIR = "Pick a dir (or make a new one: n, or o beside the selected one, in the picker)"
    RECENT_DIR = "Recent: %s/"

    def __init__(self, inbox_path, root_path, known_replicas=None):
        self.inbox_is_cloud = paths.is_cloud_path(inbox_path)
        self.root_is_cloud = paths.is_cloud_path(root_path)
        self.inbox_path = _normalized(inbox_path)
        self.root_path = _normalized(root_path)
        # Where the sorted tree's recent dirs are kept (a replicas.Replicas, saved), if anywhere
        self._known_replicas = known_replicas
        # What's changed live in the sorted tree, for its log's entry (see replicalog.py). An inbox
        # has no log: it's where files wait to be sorted, not a replica to keep track of
        self.changes = replicalog.Changes()
        for path in (self.inbox_path, self.root_path):
            if not paths.is_cloud_path(path) and not os.path.isdir(path):
                raise InboxError("%s is not a directory" % (path,))
        if any(paths.is_cloud_path(path) for path in (self.inbox_path, self.root_path)) and \
                not drivecache.exists():
            for path in (self.inbox_path, self.root_path):
                if paths.is_cloud_path(path):
                    clouddirtree.refresh_cache(paths.path_in_cloud(path))
        # Both of a kind: a move is a rename (see DirTree.move_files()). Else a move is a copy (an upload
        # or a download), then a removal from the inbox.
        self.is_same_kind = self.inbox_is_cloud == self.root_is_cloud
        inbox_parts, root_parts = paths.components(self.inbox_path), paths.components(self.root_path)
        if self.is_same_kind and root_parts[:len(inbox_parts)] == inbox_parts:
            raise InboxError("The sorted tree %s can't be in the inbox %s" % (self.root_path, self.inbox_path))
        # The inbox's relpath in the sorted tree, if it's in it (its files aren't the sorted tree's)
        self._inbox_in_root = ('/'.join(inbox_parts[len(root_parts):])
                               if self.is_same_kind and inbox_parts[:len(root_parts)] == root_parts else None)
        self._inbox_tree, self._root_tree = _tree(self.inbox_path), _tree(self.root_path)
        # Neither is removed when it's left empty, nor moved whole
        self._inbox_tree.keep_dirs([''])
        self._root_tree.keep_dirs(['' if self._inbox_in_root is None else self._inbox_in_root])
        # What Claude said of the inbox's files, by relpath (in the inbox)
        self._descriptions = {}
        self._recommendations = {}
        # The files being described (in the background), the queue of them, and the worker; and why
        # the ones that couldn't be weren't
        self._describing = set()
        # The files to say where they go of; and all the queued ones (for either)
        self._placing = set()
        self._queued = set()
        self._queue = collections.deque()
        self._worker = None
        self._state_lock = threading.Lock()
        self._failed = {}
        # The queued files to ask about anew (Ctrl-I on ones asked before), whatever Claude's cache has
        self._anew = set()
        # The describer's downloads and the screen's changes share one Drive service (not thread-safe)
        self._drive_lock = threading.Lock()
        # As a sync looks for a file where the other replica has it (elsewhere.py), the inbox's files
        # are looked for in the sorted tree, by name, size and contents, with each one's index; the
        # sorted tree's without the inbox's files, if it's in it. checked: the files compared, as a
        # sync's.
        self._inbox_index = elsewhere.Index(self._inbox_tree)
        self._root_index = elsewhere.Index(self._root_tree, excluded=self._inbox_in_root)
        self._checked = {}
        self._indexing = None
        # The inbox's files that look like junk by their names and sizes (junk.py): {relpath: why}
        self._junk_by_name = {}
        # Opens the inbox's files (Ctrl-X, or Open in the action menu)
        self._opener = opening.Opener(self._inbox_tree, self._drive_lock)
        # What the AI was last asked (see _ask_ai()), to start from next time
        self._last_instruction = ''

    # The inbox's files

    def _inbox_files(self):
        """The inbox's files' relpaths (in it), each dir's together, sorted"""
        if self.inbox_is_cloud:
            relpaths = self._inbox_tree.files_under('')
        else:
            relpaths = list(localscan.scan(self.inbox_path).files())
        return sorted(relpaths, key=lambda relpath: relpath.split('/'))

    def _is_in_inbox(self, relpath):
        """Whether the sorted tree's relpath is at or under the inbox, if the inbox is in it"""
        return self._inbox_in_root is not None and _is_at_or_under(relpath, self._inbox_in_root)

    def _size(self, relpath):
        return self._inbox_tree.file_size(relpath)

    def _cache_key(self, file):
        """What Claude said of the inbox's file is kept by its contents' hash, once it's known; else,
        or from before, by its path and size"""
        sha1 = self._inbox_tree.known_hash(file.relpath, 'sha1')
        path_key = self._path_key(file.relpath, file.size)
        return [ai.hash_key(sha1), path_key] if sha1 else [path_key]

    def _path_key(self, relpath, size):
        return ai.path_key(posixpath.join(self.inbox_path, relpath), size)

    def _load_cached(self, relpaths):
        files = [ai.File(relpath, None, self._size(relpath)) for relpath in relpaths]
        descriptions, recommendations = ai.cached(files, self._cache_key, self.root_path)
        self._descriptions.update(descriptions)
        self._recommendations.update(recommendations)

    # The screens

    def run(self):
        """Let the user pick some of the inbox's files, then choose what to do with them (_act()),
        and back to the picker, where they were, until they quit, or the inbox is empty"""
        header = ("Files in %s, to sort into %s. Pick some, then choose what to do with them." %
                  (replicanames.full(self.inbox_path), replicanames.full(self.root_path)))
        keys = (self.REFRESH_KEY if self.inbox_is_cloud else '') + hashes_screen.KEY + aiplan_screen.KEY + contextmenu.KEY + archive_screen.KEY
        # The keys row has little room: the rest are in the menu (:), and ?
        key_hints = [('Enter', 'choose what to do'), contextmenu.KEY_HINT]
        more_keys = ([aiplan_screen.KEY_HINT, archive_screen.KEY_HINT, ('Ctrl-I', 'Claude: describe, and say where they go'),
                      opening.KEY_HINT, renaming.KEY_HINT,
                      ('Ctrl-W l', 'move to the sorted tree, on the right (Ctrl-W h: back)')] +
                     ([(self.REFRESH_KEY_NAME, 'read the folder anew from Drive')] if self.inbox_is_cloud else []) +
                     [hashes_screen.KEY_HINT])
        help_lines = (picker.key_help_lines(more_keys) + ["Tags after a file's name (/ searches them too):",
                       "  [claude: ...]            what Claude says it is",
                       "  [junk? ...]              it may be removed (by its name or size, or as Claude says)"] +
                      (hashes_screen.HELP_LINES[1:] if self._jobs() else []))
        picked, selected = [], None
        while True:
            files = self._inbox_files()
            if not files:
                messages.show("The inbox is empty", ["%s has no files to sort." % (self.inbox_path,)],
                              dryrun.label())
                return
            self._load_cached(files)
            self._junk_by_name = junk.find(files, {relpath: self._size(relpath) for relpath in files})
            self._start_indexing()
            chosen = picker.pick_files(
                self.inbox_path, files, header=header, picked=picked, label=LABEL,
                keys=keys, selected=selected, key_hints=key_hints, help_lines=help_lines,
                previews=lambda send, files=files: self._send_previews(files, send),
                shown_as=lambda files=files: self._shown_as(files),
                notify_keys=DESCRIBE_KEY + OPEN_KEY, enter_picks_selection=True, twice_keys=renaming.KEY,
                side=picker.Side(self.root_path, self._side_items(), True, self._side_follow,
                                 key_hints=[('Enter', 'move the files here')]),
                none_picked_key_hints=[('Enter', 'Pick & choose what to do')],
                on_notify=lambda key, selected, picked, files=files: self._on_key(key, selected, picked, files),
                on_selection=functools.partial(elsewhere.check_contents, files, self._inbox_tree,
                                               self._inbox_index, self._root_index, self._checked,
                                               sends_previews=False))
            if chosen is None:
                self._finish_describing()
                return
            selected = chosen.selected
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
                with self._drive_lock:
                    interactive_dir_sync.refresh_replica(self._inbox_tree, selected)
                picked = chosen.files
                continue
            if chosen.key == picker.SIDE_KEY:
                # Enter in the sorted tree beside it: the picked files (or the selected one's) go there
                done = self._move_to_side([relpath for relpath in chosen.files] or
                                          [relpath for relpath in files if _is_at_or_under(relpath, selected)],
                                          chosen.side_selected)
            elif chosen.key == aiplan_screen.KEY:
                # About the picked ones, or with none picked, all of them: the AI picks (and it's told
                # where the selection is)
                done = self._ask_ai(chosen.files or files,
                                    chosen.files or (contextmenu.under(files, selected) if selected else []))
            else:
                done = self._act(chosen.files, selected)
            if done is filescreen.READ_ANEW:
                with self._drive_lock:
                    interactive_dir_sync.refresh_replica(self._inbox_tree, selected)
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
            left = [relpath for relpath in self._inbox_files()]
            selected = filescreen.shown_near(selected or '', left, files)

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
                   contextmenu.Entry('Ctrl-I', "Have Claude describe %s and say where it goes, while you go on" % (name,),
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
        with self._state_lock:
            for relpath, new in moved.items():
                for known in (self._descriptions, self._recommendations, self._failed, self._checked,
                              self._junk_by_name):
                    if relpath in known:
                        known[new] = known.pop(relpath)
        # What Claude said of each, in its cache, under its new path (the same size)
        sizes = {new: self._size(new) for new in moved.values()}
        ai.carry({self._path_key(relpath, sizes[new]): self._path_key(new, sizes[new]) for relpath, new in moved.items()})
        # Its hashes are kept under the new paths: the jobs list them there
        for job in self._jobs():
            job.scan_in_background()

    # The sorted tree beside the inbox's picker (see sidetree.py)

    def _side_items(self):
        """The sorted tree's dirs and files, for the tree beside the picker, but the inbox's, if
        it's in it"""
        return sidetree.items(self.root_path, self._root_tree, self._inbox_in_root)

    def _side_follow(self, relpath):
        """Where in the sorted tree the inbox's file at relpath is related to (for the tree beside
        the picker to show, while it's selected): Claude's dir for it, or else where a copy of it
        is, or else a file of its name; None for none (or a dir)"""
        recommendation = self._recommendations.get(relpath)
        target = self._target(relpath) if recommendation else None
        if target is not None:
            return posixpath.dirname(target)
        copies = self._copies(relpath)
        if copies:
            return copies[0]
        if self._root_index.is_built():
            named = self._root_index.files_named(posixpath.basename(relpath))
            if named:
                return sorted(named)[0]
        return None

    def _move_to_side(self, relpaths, side_relpath):
        """Move the inbox's files at relpaths into the sorted tree's dir at side_relpath (or the dir
        of the file there), Enter's in the sorted tree beside the picker, once the user confirms (see
        _approve()). Returns the ones moved, as _act() does."""
        if not relpaths:
            return None
        destination = side_relpath if self._is_sorted_dir(side_relpath) else posixpath.dirname(side_relpath)
        destination = self._not_the_inbox(destination)
        if destination is None:
            return None
        done = self._approve(self.MOVE_TO, [(relpath, _join(destination, posixpath.basename(relpath)))
                                            for relpath in relpaths])
        if done and self._known_replicas is not None:
            self._known_replicas.record_dir(self.root_path, destination)
            replicas.save(self._known_replicas)
        return done

    def _is_sorted_dir(self, relpath):
        """Whether the sorted tree's relpath is a dir (the root too)"""
        if not relpath:
            return True
        if self.root_is_cloud:
            node = self._root_tree.get_node(relpath)
            return node is not None and isinstance(node.data, entries.DirEntry)
        return os.path.isdir(os.path.join(self.root_path, relpath))

    def _trees(self):
        return [self._inbox_tree, self._root_tree]

    def _jobs(self):
        """The hashing jobs of the inbox and the sorted tree, the local ones (see hashing.py)"""
        return hashes_screen.jobs_of(self._trees())

    def prepare_hashing(self):
        """Look for the hashes of the local inbox's and sorted tree's files, and offer to hash the
        rest (see hashes_screen.offer()). Returns whether to go on. A local sorted tree's hashes are
        kept in it (see hashcache.use_replica()); the inbox's, if it's not in it, aren't (it's no
        replica)."""
        if not self.root_is_cloud:
            hashcache.use_replica(self.root_path)
        return hashes_screen.offer(hashes_screen.prepare(self._trees()))

    def _shown_as(self, relpaths):
        """{relpath: what the picker shows it as}: its name, and Claude's description, if any (or that Claude's looking at it),
        and why it looks like junk, if it does, and whether it's hashed (if the inbox is local); and
        '': the status, how far hashing got and what
        Claude is doing"""
        shown = {}
        job = hashing.job_for(self.inbox_path) if not self.inbox_is_cloud else None
        for relpath in relpaths:
            # Each (text, style): Claude's in its color, junk in a guess's yellow
            tags = []
            if relpath in self._descriptions:
                tags.append((DESCRIBED % (self._descriptions[relpath],), CLAUDE_STYLE))
            elif relpath in self._describing:
                tags.append((LOOKING, 'grey'))
            junk_reason = self._junk(relpath)
            if junk_reason is not None:
                tags.append(((JUNK_BY_NAME if relpath in self._junk_by_name else JUNK_BY_CLAUDE) % (junk_reason,),
                             'yellow'))
            if job is not None:
                tag = hashing.tag(job, relpath)
                tags.append((tag, hashing.TAG_STYLES[tag]))
            if tags:
                shown[relpath] = picker.styled([(os.path.basename(relpath), None)] +
                                               [part for tag in tags for part in (("  ", None), tag)])
        describing, placing = len(self._describing), len(self._placing)
        failed = len([relpath for relpath in relpaths if relpath in self._failed])
        busy = ["%s %s" % (what, _files(count))
                for what, count in (("describing", describing), ("placing", placing)) if count]
        status = ("Claude: " + ', '.join(busy) if busy else
                  "Claude: couldn't do %s" % (_files(failed),) if failed else '')
        # Downloading files to open them: how far it got (on the status bar, first), and each
        # file's tag
        opening.with_tags(shown, self._opener, os.path.basename)
        parts = self._opener.status_parts() + ([(status, 'yellow')] if status else [])
        shown[''] = (hashes_screen.picker_status(self._trees(), parts) if self._jobs() else
                     picker.segments(parts) if self._opener.status_parts() else status)
        return shown

    def _send_previews(self, relpaths, send):
        """Send the picker the files' previews, and again as they change (Claude's descriptions
        coming in), until it's gone"""
        sent = {}
        while True:
            changed = {relpath: lines for relpath, lines in self._previews(relpaths).items()
                       if sent.get(relpath) != lines}
            # Sent even with nothing to send: it raises PickerClosed once the picker is gone
            send(changed, default=[] if not sent else None)
            sent.update(changed)
            time.sleep(PREVIEWS_INTERVAL)

    def _previews(self, relpaths):
        """{relpath: lines} beside the picker: the file's size, what Claude said of it, where the
        sorted tree has it already, and where it goes; each under a title in its color (Claude's
        in its own, see CLAUDE_STYLE)"""
        previews = {}
        for relpath in relpaths:
            size = self._size(relpath)
            lines = [picker.styled([("Size: ", 'bold'), (text.format_size(size), None)])] if size is not None else []
            if relpath in self._descriptions:
                lines += ["", _title(DESCRIPTION_TITLE, CLAUDE_STYLE)] + _wrapped(self._descriptions[relpath], "  ")
            elif relpath in self._describing:
                lines += ["", _title(DESCRIPTION_TITLE, CLAUDE_STYLE), _grey("  Claude is looking at it...")]
            elif relpath in self._failed and relpath not in self._descriptions:
                lines += ["", _title(DESCRIPTION_TITLE + " failed", 'red')] + _wrapped(self._failed[relpath], "  ")
            lines += self._copies_lines(relpath)
            recommendation = self._recommendations.get(relpath)
            if relpath in self._junk_by_name:
                lines += ["", MAYBE_JUNK, _title("Junk? By its name or size:", 'yellow')] + \
                    _wrapped(self._junk_by_name[relpath], "  ")
            if recommendation and recommendation.get('action') == 'remove':
                if self._junk(relpath) is not None and relpath not in self._junk_by_name:
                    lines += ["", MAYBE_JUNK]
                lines += ["", _title("Recommendation (ai): remove it", CLAUDE_STYLE)] + \
                    _wrapped(recommendation.get('reason', ''), "  ")
            elif recommendation:
                # Relative to the sorted tree, so a long root doesn't hide where in it
                target = self._target(relpath)
                is_renamed = os.path.basename(target) != os.path.basename(relpath)
                lines += ["", _title(DESTINATION_TITLE, CLAUDE_STYLE)]
                lines += _wrapped(target if is_renamed else "%s/" % (os.path.dirname(target) or '.',), "  ")
                if is_renamed:
                    lines.append(_grey("  (renamed)"))
                # Why, apart from where
                lines += [""] + _wrapped(recommendation.get('reason', ''), "  ")
            elif relpath in self._placing:
                lines += ["", _title(DESTINATION_TITLE, CLAUDE_STYLE), _grey("  Claude is working it out...")]
            elif relpath in self._failed and relpath in self._descriptions:
                lines += ["", _title(DESTINATION_TITLE + " failed", 'red')] + _wrapped(self._failed[relpath], "  ")
            else:
                lines += ["", picker.styled([("Dest. path:", 'bold')]), _grey("  Ctrl-I asks Claude")]
            previews[relpath] = lines
        return previews

    def _act(self, relpaths, selected=None):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (moved, copied, removed; in a dry run, the ones it would have
        done), or None if none were (or Claude was asked, or they were opened: nothing moved); or
        filescreen.READ_ANEW to read the folder of selected (the picker's selection: a file, or a dir; by
        default the first file's) anew from Drive, as the key does."""
        if selected is None:
            selected = relpaths[0]
        node = self._inbox_tree.get_node(selected)
        folder = selected if node is None or isinstance(node.data, entries.DirEntry) else posixpath.dirname(selected)
        count = _files(len(relpaths))
        undescribed = [relpath for relpath in relpaths
                       if relpath not in self._descriptions and relpath not in self._describing]
        # The ones Claude may be asked where they go: all but the ones it's being asked of now (the
        # ones it placed, or couldn't, asked anew)
        askable = [relpath for relpath in relpaths if relpath not in self._placing]
        asked_before = [relpath for relpath in askable if relpath in self._recommendations or relpath in self._failed]
        recommended = [relpath for relpath in relpaths
                       if relpath in self._recommendations and self._target(relpath) is not None]
        # Copies of the sorted tree's files, by their contents (whatever Claude says of them), and the
        # files with candidates there not compared yet
        removable = [relpath for relpath in relpaths if self._copies(relpath)]
        junky = [relpath for relpath in relpaths if self._junk(relpath) is not None]
        uncompared = [relpath for relpath in relpaths if relpath not in self._checked and self._root_index.is_built()
                      and elsewhere.matches_of_size(relpath, self._size(relpath), self._root_index)]
        not_yet = " (%d not compared yet: Ctrl-I compares them)" % (len(uncompared),) if uncompared else ""
        destinations = sorted({os.path.dirname(self._target(relpath)) for relpath in recommended})
        renamed = [relpath for relpath in recommended
                   if os.path.basename(self._target(relpath)) != os.path.basename(relpath)]
        is_one = len(relpaths) == 1
        name = os.path.basename(relpaths[0]) if is_one else None
        # Where each option puts the files: the parts of the path, each with where it's from (see
        # _destination_lines())
        root = (self.root_path.rstrip('/') + '/', SORTED_TREE)
        claudes_dir = (((destinations[0] + '/') if destinations[0] else '', CLAUDES_DIR)
                       if len(destinations) == 1 else ("<Claude's %d dirs>/" % (len(destinations),), CLAUDES_DIR))
        claudes_name = ((os.path.basename(self._target(relpaths[0])), CLAUDES_NAME) if is_one and recommended else
                        ("<Claude's names, %d renamed>" % (len(renamed),), CLAUDES_NAME))
        own_name = (name, OWN_NAME) if is_one else ("<their own names>", OWN_NAME)
        your_dir = ("<a dir you pick>/", YOUR_DIR)
        inbox_root = (self.inbox_path.rstrip('/') + '/', THE_INBOX)
        typed = ("<a name you type>", YOUR_NAME)
        it = "it" if is_one else _of(len(recommended), len(relpaths))
        they = "it" if is_one else "the %s" % (count,)
        def path_of(*parts):
            return ''.join(text for text, _ in parts)

        def to_a_dir(action):
            return lambda: self._to_a_dir(action, relpaths, renamed, count)
        actions = collections.OrderedDict([
            (self.ASK_AI, _Action("Ask AI what to do with %s, and review its plan" % (they,), None, ASK, [],
                                  lambda: self._ask_ai(relpaths, relpaths))),
            (self.DESCRIBE, _Action("Describe %s with Claude, while you go on (sends it their contents)" %
                                    ("it" if is_one else _of(len(undescribed), len(relpaths)),),
                                    None if undescribed else "described", ASK, [],
                                    lambda: self.describe_in_background(undescribed))),
            # As Ctrl-I: the ones Claude placed already are asked about anew (they may have changed)
            (self.RECOMMEND, _Action("Ask Claude where %s go%s in %s, while you go on%s" %
                                     ("it" if is_one else _of(len(askable), len(relpaths)), "es" if is_one else "",
                                      self.root_path, (" (anew: %s before)" % ("asked" if is_one else
                                                                               "%d asked" % (len(asked_before),)))
                                      if asked_before else ""),
                                     None if askable else "being asked", ASK, [],
                                     lambda: self.ask_in_background(askable, anew=True))),
            (self.MOVE_RECOMMENDED, _Action("Move %s to Claude's recommendation: %s" %
                                            (it, path_of(root, claudes_dir, claudes_name))
                                            if is_one or len(destinations) == 1 else
                                            "Move %s to Claude's recommendations (%d dirs%s)" %
                                            (it, len(destinations), ", %d renamed" % (len(renamed),) if renamed else ""),
                                            None if recommended else "no recommendation", MOVE,
                                            [root, claudes_dir, claudes_name],
                                            lambda: self._approve(self.MOVE_TO, [(relpath, self._target(relpath))
                                                                                 for relpath in recommended]))),
            (self.MOVE_TO_CLAUDES_DIR, _Action("Move %s to Claude's dir, keeping %s name: %s" %
                                               (it, "its" if is_one else "their", path_of(root, claudes_dir, own_name)),
                                               None if renamed else "the same as Claude's recommendation", MOVE,
                                               [root, claudes_dir, own_name],
                                               lambda: self._to_claudes_dir(recommended))),
            (self.MOVE_TO_CLAUDES_DIR_TYPED, _Action("Move it to Claude's dir, under a name you type: %s" %
                                                     (path_of(root, claudes_dir, typed),),
                                                     None if is_one and recommended else "not one file with a recommendation",
                                                     MOVE, [root, claudes_dir, typed],
                                                     lambda: self._to_claudes_dir(recommended, is_typed=True))),
            (self.MOVE_TO, _Action("Move %s to a dir you pick: %s" % (they, path_of(root, your_dir, own_name)),
                                   None, MOVE, [root, your_dir, own_name], to_a_dir(self.MOVE_TO))),
            (self.MOVE_TO_CLAUDES_NAMES, _Action("Move %s to a dir you pick, under Claude's %s: %s" %
                                                 (they, "name" if is_one else "names",
                                                  path_of(root, your_dir, claudes_name)),
                                                 None if renamed else "no other name from Claude", MOVE,
                                                 [root, your_dir, claudes_name], to_a_dir(self.MOVE_TO_CLAUDES_NAMES))),
            (self.MOVE_TO_TYPED, _Action("Move it to a dir you pick, under a name you type: %s" %
                                         (path_of(root, your_dir, typed),),
                                         None if is_one else "not one file", MOVE, [root, your_dir, typed],
                                         to_a_dir(self.MOVE_TO_TYPED))),
            (self.MOVE_IN_INBOX, _Action("Move %s to another dir in the inbox, a dir you pick: %s" %
                                         (they, path_of(inbox_root, your_dir, own_name)),
                                         None, MOVE, [inbox_root, your_dir, own_name],
                                         lambda: self._to_a_dir_in_inbox(relpaths, count))),
            (self.COPY_TO, _Action("Copy %s to a dir you pick (keeping %s in the inbox): %s" %
                                   (they, "it" if is_one else "them", path_of(root, your_dir, own_name)),
                                   None, COPY, [root, your_dir, own_name], to_a_dir(self.COPY_TO))),
            (self.REMOVE_COPIES, _Action("Remove %s: %s in %s%s" %
                                         ("it" if is_one else _of(len(removable), len(relpaths)),
                                          "a copy of a file" if is_one else "copies of files", self.root_path, not_yet),
                                         None if removable else "not a copy", REMOVE, [],
                                         lambda: self._remove(removable, ["  %s: a copy of %s" % (relpath, ', '.join(
                                             _join(self.root_path, copy) for copy in self._copies(relpath)[:2]))
                                             for relpath in removable]), acted_on=removable)),
            (self.REMOVE_JUNK, _Action("Remove %s: %s like junk (to %s)" %
                                       ("it" if is_one else _of(len(junky), len(relpaths)),
                                        "it looks" if is_one or len(junky) == 1 else "they look",
                                        "Drive's trash" if self.inbox_is_cloud else "the trash"),
                                       None if junky else "not junk", REMOVE, [],
                                       lambda: self._remove(junky, ["  %s: %s" % (relpath, self._junk(relpath))
                                                                    for relpath in junky], to_trash=True),
                                       acted_on=junky)),
            # Not when it does what removing the copies does (all of them are), or the junk does
            # (all of them are, in Drive, where both go to its trash)
            (self.REMOVE, _Action("Remove %s from %s" % (they, self.inbox_path),
                                  "the same as removing the copies" if len(removable) == len(relpaths) else
                                  "the same as removing the junk" if self.inbox_is_cloud and len(junky) == len(relpaths) else
                                  None, REMOVE, [], lambda: self._remove(relpaths))),
            (self.EXPLORE, _Action("Explore it: what's in the zip", None if is_one and archives.is_archive(relpaths[0]) else
                                   "not a zip", OPEN, [], lambda: self._explore(relpaths[0], set(relpaths)),
                                   said=(OPEN, " look in it, unpacking nothing"))),
            (self.OPEN, _Action("Open %s with %s program%s" %
                                (they, "its" if is_one else "their", "" if is_one else "s"),
                                None if len(relpaths) <= opening.MAX_OPENED else "too many", OPEN, [],
                                lambda: self._open(relpaths))),
            (self.READ_ANEW, _Action("Read %s/ anew from Google Drive" % (_join(self.inbox_path, folder),),
                                     None if self.inbox_is_cloud else "not Drive's", READ, [],
                                     lambda: filescreen.READ_ANEW, acted_on=[(folder or '.') + '/'])),
        ])
        # The ones that can't be done aren't offered, nor one that does the same as another (Claude's
        # dir under the file's own name, when Claude keeps the name)
        offered = collections.OrderedDict((key, action) for key, action in actions.items() if action.why_not is None)
        # Similar actions together, a blank line between each kind (opening and reading anew, the
        # picker's keys, together)
        kinds = [(ASK,), (MOVE,), (COPY,), (REMOVE,), (OPEN, READ)]
        # Each in its verb's color, the parts saying where the files go in their sources' (as the
        # brackets below the menu), after its key, if a picker's key does it too
        prefixes = picker.shortcut_prefixes([self.NOTHING] + [action.label for action in offered.values()],
                                            {action.label: self.SHORTCUTS[key] for key, action in offered.items()
                                             if key in self.SHORTCUTS})
        choices = picker.grouped([[picker.Option(self.NOTHING, self.NOTHING, prefixes[self.NOTHING] + self.NOTHING)]] + [
            [picker.Option(key, action.label, prefixes[action.label] + _option_text(action.label, VERB_COLORS[action.verb], action.parts))
             for key, action in offered.items() if action.verb in kind] for kind in kinds])
        lines = {key: (self._said_lines(*action.said) if action.said else
                       self._destination_lines(action.verb, action.parts, relpaths, action.acted_on or relpaths))
                 for key, action in offered.items()}
        lines[self.ASK_AI] = self._said_lines(ASK, " tell it what to do; it answers with a plan to review")
        header = ("%s, in %s: what to do with it?" % (name, posixpath.dirname(posixpath.join(self.inbox_path, relpaths[0])))
                  if is_one else "%s picked in %s. What to do with them?" % (count, self.inbox_path))
        chosen = offered.get(picker.pick_option(choices, header=header, title="What to do", label=LABEL, previews_below=lines))
        return chosen.run() if chosen is not None else None

    def _said_lines(self, verb, text):
        """The lines below the menu for an option that says what it does in its own words"""
        return [picker.segments([(" %s " % (verb.upper(),), VERB_COLORS[verb]), (text, None)])]

    def _open(self, relpaths):
        if opening.confirm(self._opener, relpaths, relpaths, LABEL):
            self.open_in_background(relpaths, relpaths)

    def _to_a_dir_in_inbox(self, relpaths, count):
        destination = self._pick_dir('move', count, in_inbox=True)
        return None if destination is None else self._move_in_inbox(relpaths, destination)

    def _to_claudes_dir(self, recommended, is_typed=False):
        """Move the recommended files to the dirs Claude says, each under its own name, or (is_typed:
        one file) one the user types"""
        plan = [(relpath, _join(os.path.dirname(self._target(relpath)), os.path.basename(relpath)))
                for relpath in recommended]
        if is_typed:
            plan = self._typed_name(plan)
        return None if plan is None else self._approve(self.MOVE_TO, plan)

    def _to_a_dir(self, action, relpaths, renamed, count):
        """Move or copy (action) the files to a dir the user chooses, under their own names, Claude's
        (for the ones it renamed: MOVE_TO_CLAUDES_NAMES) or one typed (MOVE_TO_TYPED); offered first
        next time, if they went"""
        destination = self._choose_dir('copy' if action == self.COPY_TO else 'move', count)
        if destination is None:
            return None
        names = {relpath: os.path.basename(self._target(relpath) if relpath in renamed and action == self.MOVE_TO_CLAUDES_NAMES
                                           else relpath) for relpath in relpaths}
        plan = [(relpath, _join(destination, names[relpath])) for relpath in relpaths]
        if action == self.MOVE_TO_TYPED:
            plan = self._typed_name(plan)
            if plan is None:
                return None
        done = self._approve(self.COPY_TO if action == self.COPY_TO else self.MOVE_TO, plan)
        if done and self._known_replicas is not None:
            self._known_replicas.record_dir(self.root_path, destination)
            replicas.save(self._known_replicas)
        return done

    def _destination_lines(self, verb, parts, relpaths, acted_on):
        """The lines below the menu for an option: what it does to the files (verb, see VERB_COLORS),
        as a label in its color, and where it puts them (parts: the path's, each (text, where it's
        from)), and under the path, a bracket under each part saying where it's from, in that one's
        color (see SORTED_TREE)"""
        verb_label = " %s " % (verb.upper(),)
        if not parts:
            what = (os.path.basename(acted_on[0]) if len(acted_on) == 1 else _files(len(acted_on)))
            text = {ASK: " Claude, about %s, while you go on" % (what,),
                    REMOVE: " %s, from %s%s" % (what, self.inbox_path,
                                                " (to the trash)" if verb == REMOVE and not self.inbox_is_cloud else ""),
                    OPEN: " %s, with %s program%s" % (what, "its" if len(acted_on) == 1 else "their",
                                                      "" if len(acted_on) == 1 else "s"),
                    READ: " %s, in %s, anew from Google Drive" % (acted_on[0], self.inbox_path)}
            return [picker.segments([(verb_label, VERB_COLORS[verb]), (text.get(verb, ''), None)])]
        parts = _fitting(parts, shutil.get_terminal_size().columns - 1 - picker.display_width(verb_label) - 1)
        path_line = picker.segments([(verb_label, VERB_COLORS[verb]), (" ", None)] +
                                    [(text, None) for text, _ in parts])
        brackets = [(" " * (picker.display_width(verb_label) + 1), None)]
        for text, (color, names) in parts:
            brackets.append((_bracket(names, picker.display_width(text)), color))
        return [path_line, picker.segments(brackets)]

    def _typed_name(self, plan):
        """plan (one file: [(relpath, its path in the sorted tree)]) with the name the user types for
        it there, starting as Claude's (or its own); None if they typed none, or one that can't be"""
        (relpath, target), = plan
        recommendation = self._recommendations.get(relpath)
        default = os.path.basename(self._target(relpath) if recommendation and self._target(relpath)
                                   else relpath)
        lines = ["Moving %s" % (posixpath.join(self.inbox_path, relpath),),
                 "to %s/" % (_join(self.root_path, os.path.dirname(target)),)]
        if relpath in self._descriptions:
            lines.append(DESCRIBED % (self._descriptions[relpath],))
        lines += ["", "Its name there (Enter to keep it as it is; an empty one, or Ctrl-C, to go back):"]
        name = messages.ask("The file's name in %s" % (self.root_path,), lines, "> ", default, dryrun.label())
        if name is None:
            return None
        if '/' in name or name in ('.', '..'):
            messages.show("Not a name", ["%r can't be a file's name: it's a name, without '/'." % (name,)],
                          dryrun.label(), 'red')
            return None
        return [(relpath, _join(os.path.dirname(target), name))]

    def _junk(self, relpath):
        """Why the inbox's file at relpath looks like junk: by its name and size (junk.py), or as
        Claude says (a recommendation to remove it that isn't for a copy); None if it doesn't"""
        if relpath in self._junk_by_name:
            return self._junk_by_name[relpath]
        recommendation = self._recommendations.get(relpath)
        if recommendation and recommendation.get('action') == 'remove' and not recommendation.get('copies'):
            return recommendation.get('reason') or "Claude says so"
        return None

    def _copies(self, relpath):
        """The sorted tree's files (relpaths in it) with the same contents as the inbox's at relpath,
        of the ones compared, and the ones of its hash, if it's known (see elsewhere.known_same())"""
        copies = {match for match, is_same in self._checked.get(relpath, {}).items() if is_same}
        copies |= {match for match, is_same in elsewhere.known_same(relpath, self._inbox_index,
                                                                    self._root_index).items() if is_same}
        return sorted(copies)

    def _copies_lines(self, relpath):
        """A preview's lines of what the sorted tree has of the inbox's file at relpath: its copies,
        or that it has none, or its candidates (to compare when it's selected)"""
        copies = self._copies(relpath)
        title = (IN_SORTED_TREE_TITLE + " ", 'bold,' + CLAUDE_STYLE)
        if copies:
            return (["", picker.styled([title, ("Yes", 'bold,green')])] +
                    [line for copy in copies[:3] for line in _wrapped_path(_join(self.root_path, copy), "    ")] +
                    [SURELY_A_COPY])
        if relpath in self._checked:
            return ["", picker.styled([title, ("No", 'bold,red'), (" (contents compared)", 'grey')])]
        if not self._root_index.is_built():
            return ["", picker.styled([title]), _grey("  Looking through the sorted tree...")]
        candidates = elsewhere.matches_of_size(relpath, self._size(relpath), self._root_index)
        if candidates:
            return ["", picker.styled([title]), _grey("  %s of its size there:" % (_files(len(candidates)),)),
                    _grey("  compared when it's selected")]
        # None of its size (nor of its hash) there
        return ["", picker.styled([title, ("No", 'bold,red')])]

    def _start_indexing(self):
        """List the sorted tree's files (its index), in the background, once"""
        if self._indexing is None:
            self._indexing = threading.Thread(target=self._build_index, daemon=True)
            self._indexing.start()

    def _build_index(self):
        try:
            self._root_index.build()
        except Exception:
            # Only for finding copies: without it, there are none to say
            pass

    # Claude

    def describe_in_background(self, relpaths):
        """Have Claude describe the files at relpaths (see ask_in_background())"""
        self.ask_in_background(relpaths, False)

    def ask_in_background(self, relpaths, place=True, anew=False):
        """Have Claude describe the files at relpaths that have no description, and with place, say
        where they go (what Enter's "Ask Claude where" did, and Ctrl-I does): their contents are
        compared with the sorted tree's files first, so Claude knows which are copies. On a thread
        of its own, a batch at a time, while the user goes on: each picker shows them as they come.
        With anew (Ctrl-I's), the ones asked about before are asked again, and compared again, since
        they (or the sorted tree) may have changed: what Claude said of them, here and in its cache,
        is dropped (but for the ones being asked about now)."""
        with self._state_lock:
            for relpath in relpaths:
                if anew and relpath not in self._queued:
                    self._forget(relpath)
                needs_description = relpath not in self._descriptions
                needs_place = place and relpath not in self._recommendations
                if not (needs_description or needs_place):
                    continue
                self._failed.pop(relpath, None)
                if needs_place:
                    self._placing.add(relpath)
                if relpath in self._queued:
                    continue
                self._queued.add(relpath)
                self._queue.append(relpath)
                if needs_description:
                    self._describing.add(relpath)
            if self._queue and self._worker is None:
                self._worker = threading.Thread(target=self._ask_queued, daemon=True)
                self._worker.start()

    def _forget(self, relpath):
        """Drop what's known of the inbox's file at relpath, to ask Claude about it anew (with the
        state lock)"""
        if (relpath in self._descriptions or relpath in self._recommendations or relpath in self._failed or
                relpath in self._checked):
            self._anew.add(relpath)
        self._descriptions.pop(relpath, None)
        self._recommendations.pop(relpath, None)
        self._failed.pop(relpath, None)
        self._checked.pop(relpath, None)

    def _ask_queued(self):
        """Ask Claude about the queued files, a batch at a time, until there are none (on the
        worker's thread: nothing is printed, as a picker may have the screen)"""
        while True:
            with self._state_lock:
                if not self._queue:
                    self._worker = None
                    return
                batch = [self._queue.popleft() for _ in range(min(ai.BATCH_SIZE, len(self._queue)))]
            try:
                self._describe(batch)
                self._place([relpath for relpath in batch if relpath in self._placing])
            finally:
                with self._state_lock:
                    self._describing.difference_update(batch)
                    self._placing.difference_update(batch)
                    self._queued.difference_update(batch)
                    self._anew.difference_update(batch)

    def _describe(self, batch):
        """Have Claude describe the files of batch that have no description (on the worker's thread)"""
        relpaths = [relpath for relpath in batch if relpath not in self._descriptions]
        try:
            if relpaths:
                with self._drive_lock:
                    files = self._ai_files(relpaths, is_quiet=True)
                found = ai.describe(files, self._cache_key, anew=self._anew & set(relpaths))
                self._descriptions.update(found)
                for relpath in relpaths:
                    if relpath not in found:
                        self._failed[relpath] = "Claude gave no description of it."
        except Exception as error:
            for relpath in relpaths:
                self._failed[relpath] = str(error)
        finally:
            with self._state_lock:
                self._describing.difference_update(batch)

    def _place(self, relpaths):
        """Have Claude say where the files at relpaths go, by their descriptions and which are copies
        of the sorted tree's files (their contents compared first), on the worker's thread"""
        relpaths = [relpath for relpath in relpaths if relpath not in self._recommendations]
        if not relpaths:
            return
        try:
            self._compare(relpaths)
            files = [ai.File(relpath, None, self._size(relpath)) for relpath in relpaths]
            found = ai.recommend(files, self._cache_key, self._root_dirs(), self.root_path, self._descriptions,
                                 {relpath: self._copies(relpath) for relpath in relpaths},
                                 anew=self._anew & set(relpaths))
            self._recommendations.update(found)
            for relpath in relpaths:
                if relpath not in found:
                    self._failed[relpath] = "Claude didn't say where it goes."
        except Exception as error:
            for relpath in relpaths:
                self._failed[relpath] = str(error)

    def _compare(self, relpaths):
        """Compare the contents of the inbox's files at relpaths with their candidates in the sorted
        tree, the ones not compared yet (once the sorted tree is listed)"""
        self._start_indexing()
        self._indexing.join()
        elsewhere.check_all(relpaths, self._inbox_tree, self._inbox_index, self._root_index, self._checked)

    def wait_for_claude(self):
        """Wait for what Claude is asked of files, without a screen (e.g. for a test)"""
        while True:
            worker = self._worker
            if worker is None:
                return
            worker.join()

    def _finish_describing(self):
        """Wait for what Claude is asked of files, if anything, on a progress screen (Ctrl-C stops
        waiting: what it said so far is kept)"""
        if not self._queued:
            return
        title = ("Waiting for Claude to finish with %s (what it said so far is kept)" %
                 (_files(len(self._queued)),))
        failed_before = len(self._failed)
        with messages.progress_screen(title, dryrun.label(), wait=False):
            try:
                while self._queued:
                    messages.print_progress("%s left (%d being described, %d placed), %d failed" % (
                        _files(len(self._queued)), len(self._describing),
                        len(self._queued) - len(self._describing), len(self._failed) - failed_before))
                    time.sleep(DESCRIBED_WAIT_INTERVAL)
            except KeyboardInterrupt:
                messages.note_stopped()
        if len(self._failed) > failed_before:
            messages.show("Claude couldn't finish with %s" % (_files(len(self._failed) - failed_before),),
                          [list(self._failed.values())[-1]], dryrun.label(), 'red')

    def _ai_files(self, relpaths, is_quiet=False):
        """ai.File of each of the inbox's files at relpaths: a Drive one downloaded first (one at a
        time; or found downloaded, see downloads.py), unless it's too big to be read, or a Google
        file. With is_quiet, it prints nothing (a picker may have the screen)."""
        files = []
        for number, relpath in enumerate(relpaths, 1):
            size = self._size(relpath)
            local_path = None
            if not self.inbox_is_cloud:
                local_path = os.path.join(self.inbox_path, relpath)
            elif (size or 0) <= ai.MAX_READ_SIZE and self._inbox_tree.cant_fetch(relpath) is None:
                if not is_quiet:
                    messages.print_progress("Downloading %d of %d files for Claude: %s" %
                                            (number, len(relpaths), relpath))
                try:
                    local_path = self._downloaded(relpath)
                except OSError as error:
                    if not is_quiet:
                        messages.print_line("Couldn't download %s (%s): Claude goes by its name" %
                                            (relpath, error), "yellow")
                    local_path = None
            files.append(ai.File(relpath, local_path, size))
        return files

    def _root_dirs(self):
        """{dir relpath: the names of a few of its files (NAMES_PER_DIR)} of the sorted tree's dirs
        ('' its root), so Claude sees how they're named; not the inbox's (if it's in it)"""
        dirs = {'': []}
        if self.root_is_cloud:
            found = [(child.identifier, isinstance(child.data, entries.DirEntry))
                     for child in self._root_tree.nodes_under('') if child.identifier]
        else:
            found = [(relpath, kind == localscan.DIR) for relpath, (kind, _, _) in localscan.scan(self.root_path).entries.items()]
        found = [(relpath, is_dir) for relpath, is_dir in found
                 if self._inbox_in_root is None or not _is_at_or_under(relpath, self._inbox_in_root)]
        for relpath, is_dir in sorted(found):
            if is_dir:
                dirs.setdefault(relpath, [])
        for relpath, is_dir in sorted(found):
            names = dirs.get(os.path.dirname(relpath))
            if not is_dir and names is not None and len(names) < NAMES_PER_DIR:
                names.append(os.path.basename(relpath))
        return dirs

    # Opening a file

    def _on_key(self, key, selected, picked, files):
        """A notify key pressed in the picker of files (on another thread): Ctrl-X opens the
        selected file (not the picked ones: the menu's Open does, see opening.confirm()), Ctrl-I asks Claude about the picked ones (or the selected one, or
        a dir's)"""
        if key == OPEN_KEY:
            # The selected one only (the picked ones: the menu's Open, which downloads them first)
            self._opener.press([selected], files)
        else:
            self.ask_in_background(picked or [relpath for relpath in files if _is_at_or_under(relpath, selected)],
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
        key_hints = [('Enter', 'this dir'), (self.NEW_DIR_KEY, 'a new dir in it'), ('o/O', 'a new dir beside it'),
                     renaming.KEY_HINT]
        while True:
            if is_cloud:
                root = clouddirtree.factory(base)
                picked = picker.pick_from_tree(root, header=header, dirs_only=True, root_name=base,
                                               keys=keys, key_hints=key_hints, twice_keys=renaming.KEY)
                key, relpath = (picked[0], picked[1][0].relpath) if picked else ('', None)
            else:
                picked = picker.pick_under_dir(base, dirs_only=True, lazy=True, header=header,
                                               keys=keys, key_hints=key_hints, twice_keys=renaming.KEY)
                key, relpath = (picked[0], _relpath(picked[1], base)) if picked else ('', None)
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
        return relpath if in_inbox else self._not_the_inbox(relpath)

    def _rename_sorted_dir(self, relpath):
        """cc in the dir picker: rename the sorted tree's dir at relpath (see renaming.py), but the
        inbox's, or one it's in"""
        if self._inbox_in_root is not None and _is_at_or_under(self._inbox_in_root, relpath):
            messages.show("Can't rename it", ["The inbox is in %s/: rename another dir." % (_join(self.root_path, relpath),)],
                          dryrun.label())
            return
        with self._drive_lock:
            renamed = renaming.rename(self._root_tree, relpath, LABEL)
        if renamed is None or dryrun.DRYRUN:
            return
        _, moves = renamed
        self.changes.note(self.root_path, 'moved', len(moves))

    def _new_dir(self, parent, verb, count, base=None):
        """The relpath of a new dir in the sorted tree's (or base's, the inbox's) dir at parent, its
        name typed (a/b: one in a new one), to move or copy (verb) the files (count) to; it's made
        when they go there. None if no name, or one that can't be, was typed."""
        base = base or self.root_path
        name = messages.ask("A new dir in %s/" % (_join(base, parent),),
                            ["The new dir to %s the %s to, in %s/" % (verb, count, _join(base, parent)),
                             "(a/b makes b in a new a). An empty name, or Ctrl-C, goes back."],
                            "> ", label=dryrun.label())
        if name is None:
            return None
        parts = name.strip('/').split('/')
        if any(part in ('', '.', '..') for part in parts):
            messages.show("Not a dir's name", ["%r can't be a new dir's name." % (name,)], dryrun.label(), 'red')
            return None
        return _join(parent, *parts)

    def _not_the_inbox(self, relpath):
        """relpath (a dir in the sorted tree), unless it's the inbox or in it (then it says so, and
        it's None)"""
        if relpath is not None and self._is_in_inbox(relpath):
            messages.show("That's the inbox", ["Pick a dir of %s that isn't in the inbox." % (self.root_path,)],
                          dryrun.label())
            return None
        return relpath

    def _ai_task(self, relpaths, focus):
        """What to ask the AI about the inbox's files at relpaths, the user being on those of focus (see
        aiplan.py): what's known of each, and the sorted tree's dirs"""
        def in_sorted_tree(relpath, target):
            if self._is_in_inbox(target):
                return "that's in the inbox"
            return "there's a file or dir there already" if self._root_tree.exists(target) else None

        def in_inbox(relpath, target):
            return "there's a file or dir there already" if self._inbox_tree.exists(target) else None
        where = "its path relative to the root of the sorted tree"
        actions = [aiplan.Action(self.MOVE_TO, "Move to the sorted tree", "move the file into the sorted tree: %s." % (where,),
                                 True, False, in_sorted_tree),
                   aiplan.Action(self.COPY_TO, "Copy to the sorted tree",
                                 "copy the file to the sorted tree, keeping it in the inbox: %s." % (where,),
                                 True, False, in_sorted_tree),
                   aiplan.Action(self.MOVE_IN_INBOX, "Move in the inbox",
                                 "move or rename the file in the inbox: its path relative to the inbox.",
                                 True, False, in_inbox),
                   aiplan.Action(self.REMOVE, "Remove from the inbox", "remove the file from the inbox.")]
        files = []
        for relpath in relpaths:
            notes = ([self._descriptions[relpath]] if relpath in self._descriptions else [])
            copies = self._copies(relpath)
            if copies:
                notes.append("the sorted tree has the same contents at %s" % (', '.join(copies[:3]),))
            if self._junk(relpath) is not None:
                notes.append("looks like junk: %s" % (self._junk(relpath),))
            files.append(aiplan.File(relpath, self._size(relpath), '; '.join(notes)))
        dirs = self._root_dirs()
        listed = ["%s%s" % (dirpath or '. (the root)', " (e.g. %s)" % (', '.join(dirs[dirpath]),) if dirs[dirpath] else "")
                  for dirpath in sorted(dirs)[:ai.MAX_DIRS_GIVEN]]
        return aiplan.Task("These are files in the inbox %s, of files waiting to be sorted into the sorted tree %s." %
                           (self.inbox_path, self.root_path), files, actions,
                           context=["The sorted tree's dirs, with a few of the names of the files in each:"] + listed,
                           focus=focus, fetch=lambda relpath: self._opener.local_path(relpath, ai.MAX_READ_SIZE))

    def _ask_ai(self, relpaths, focus=()):
        """Ask the AI about the inbox's files at relpaths, the user being on those of focus, and do what
        the user approves of its plan, if it answers with one (each kind once they confirm it, as if
        they chose it). Returns the ones done (in a
        dry run, the ones it would have done), or None if none were."""
        self._last_instruction, steps = aiplan_screen.ask(self._ai_task(relpaths, focus), self._last_instruction, LABEL)
        if not steps:
            return None
        done = []
        for action in (self.MOVE_TO, self.COPY_TO):
            plan = [(step.relpath, step.target) for step in aiplan_screen.of_action(steps, action)]
            if plan:
                done += self._approve(action, plan, is_reviewed=True) or []
        moves = [(step.relpath, step.target) for step in aiplan_screen.of_action(steps, self.MOVE_IN_INBOX)]
        if moves:
            done += self._move_plan_in_inbox(moves, self.inbox_path) or []
        removed = aiplan_screen.of_action(steps, self.REMOVE)
        if removed:
            done += self._remove([step.relpath for step in removed],
                                 ["  %s: %s" % (step.relpath, step.reason) for step in removed], to_trash=True) or []
        return done or None

    def _approve(self, action, plan, is_reviewed=False):
        """Show where each file of plan (relpath, its path in the sorted tree: a dir and a name, maybe
        another) goes, as the tree it makes (unless is_reviewed: it was), then, once the user confirms,
        move (MOVE_TO) or copy them there. Returns the picked files done (or that would have been, in a
        dry run), or None if the user didn't confirm."""
        verb = "Move" if action == self.MOVE_TO else "Copy"
        targets = {}
        for relpath, target in plan:
            targets.setdefault(target, []).append(relpath)
        clashes = {target: sources for target, sources in targets.items() if len(sources) > 1}
        if clashes:
            target = sorted(clashes)[0]
            messages.show("Files of the same name",
                          ["%d files would go to %s: %s. Pick them apart." %
                           (len(clashes[target]), _join(self.root_path, target), ', '.join(clashes[target]))],
                          dryrun.label(), 'red')
            return None
        destinations = sorted({os.path.dirname(target) for _, target in plan})
        new_dirs = [destination for destination in destinations
                    if not self._root_tree.exists(destination)]
        previews = {}
        for target, (relpath,) in targets.items():
            lines = ["From: %s" % (posixpath.join(self.inbox_path, relpath),)]
            if self._root_tree.exists(target):
                lines += ["", "There's a file there already:", "it's skipped."]
            if os.path.dirname(target) in new_dirs:
                lines += ["", "In a new dir."]
            if os.path.basename(target) != os.path.basename(relpath):
                lines += ["", "Renamed, from:"] + _wrapped(os.path.basename(relpath), "  ")
            recommendation = self._recommendations.get(relpath)
            if recommendation and self._target(relpath) == target:
                lines += ["", "Why (Claude):"] + _wrapped(recommendation.get('reason', ''), "  ")
            previews[target] = lines
        summary = ("%s %s from %s into %d dirs of %s%s" %
                   (verb, _files(len(plan)), self.inbox_path, len(destinations), self.root_path,
                    " (%d of them new)" % (len(new_dirs),) if new_dirs else ""))
        header = "%s, where shown (beside each: where it's from). Look them through." % (summary,)
        if not is_reviewed and not picker.view_files(self.root_path, sorted(targets, key=lambda target: target.split('/')),
                                 header=header, previews=previews, label=LABEL,
                                 key_hints=[('Enter', 'go on to say yes or no'), ('q', 'back to the inbox')]):
            return None
        lines = [summary + "?"]
        if not self.is_same_kind:
            lines.append("(%s %s, then %s from the inbox%s, once each is there.)" % (
                "Uploaded to Google Drive" if self.root_is_cloud else "Downloaded from Google Drive",
                "and removed" if action == self.MOVE_TO else "", "" if action == self.MOVE_TO else "kept in",
                " (to Drive's trash)" if self.inbox_is_cloud and action == self.MOVE_TO else ""))
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, LABEL):
            return None
        moves = list(plan)
        # The cache's keys of each file, here and where it goes (the same size), while it's here
        sizes = {relpath: self._size(relpath) for relpath, _ in plan}
        keys = {relpath: (self._path_key(relpath, sizes[relpath]),
                          ai.path_key(posixpath.join(self.root_path, target), sizes[relpath]))
                for relpath, target in plan}
        # Once it's done (or stopped), Enter goes back to the picker, so what was done can be read
        done = None
        with messages.progress_screen(summary + (" (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock:
            if self.is_same_kind:
                done = (self._inbox_tree.move_files(moves, self._root_tree) if action == self.MOVE_TO else
                        self._inbox_tree.copy_files_within(moves, self._root_tree))
            else:
                done = self._transfer(moves, action == self.MOVE_TO)
        if dryrun.DRYRUN:
            return [relpath for relpath, _ in plan]
        if done is None:
            # Stopped (Ctrl-C) before it said: the ones in the sorted tree now (and, moved, out of
            # the inbox; one copied but not removed yet is still the inbox's)
            done = [(relpath, new_relpath) for relpath, new_relpath in moves if self._root_tree.has_file(new_relpath)
                    and (action != self.MOVE_TO or not self._inbox_tree.has_file(relpath))]
        done_sources = {relpath for relpath, _ in done}
        done = [relpath for relpath, _ in plan if relpath in done_sources]
        # What Claude said of each goes with it, to its new path
        ai.carry(dict(keys[relpath] for relpath in done))
        if action == self.MOVE_TO:
            # Only the sorted tree's log says so: files leaving the inbox for it is what an inbox is
            # for, not a change of the inbox to keep in its own log
            self.changes.note(self.root_path, 'added', len(done), self.inbox_path)
        else:
            self.changes.note(self.root_path, 'copied', len(done), self.inbox_path)
        not_done = [relpath for relpath, _ in plan if relpath not in set(done)]
        if not_done:
            self._say_not_done("moved" if action == self.MOVE_TO else "copied", not_done, len(plan))
        return done

    def _move_in_inbox(self, relpaths, destination):
        """Move the inbox's files at relpaths to its dir at destination (a relpath in it), under their
        own names, once the user confirms; what's known of them goes with them. Returns the ones
        moved (in a dry run, the ones it would move), or None if none were."""
        plan = [(relpath, _join(destination, posixpath.basename(relpath))) for relpath in relpaths
                if posixpath.dirname(relpath) != destination]
        where = _join(self.inbox_path, destination)
        if not plan:
            messages.show("Can't move them there", ["%s/ has them already." % (where,)], dryrun.label(), 'red')
            return None
        return self._move_plan_in_inbox(plan, where)

    def _move_plan_in_inbox(self, plan, where):
        """Move the inbox's files, each of plan (relpath, its new one in the inbox), to where (what to
        call it), once the user confirms; what's known of them goes with them. Returns the ones moved
        (in a dry run, the ones it would move), or None if none were."""
        there = [target for _, target in plan if self._inbox_tree.exists(target)]
        if there:
            messages.show("Can't move them there",
                          ["%s/ has a file or dir of the same name already:" % (where,)] +
                          ["  " + target for target in there[:filescreen.MAX_FILES_LISTED]],
                          dryrun.label(), 'red')
            return None
        lines = ["Move %s to %s/?" % (_files(len(plan)), where)]
        lines += text.listed(["  " + relpath for relpath, _ in plan], filescreen.MAX_FILES_LISTED)
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, LABEL):
            return None
        # Stopped (Ctrl-C) before move_files() says (it says how far it got, if it's stopped in it)
        done = []
        with messages.progress_screen("Moving %s in %s%s" % (_files(len(plan)), self.inbox_path,
                                                             " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock:
            done = self._inbox_tree.move_files([(relpath, target) for relpath, target in plan])
        if dryrun.DRYRUN:
            return [relpath for relpath, _ in plan]
        moved = {relpath: new for relpath, new in done}
        self._carry(moved)
        not_done = [relpath for relpath, _ in plan if relpath not in moved]
        if not_done:
            self._say_not_done("moved", not_done, len(plan))
        return list(moved) or None

    def _say_not_done(self, what, relpaths, count):
        """Show that the inbox's files at relpaths (of count) weren't moved, copied or removed (what)"""
        messages.show("Not all were %s" % (what,),
                      ["%d of the %s couldn't be %s (they're still in %s):" % (
                          len(relpaths), _files(count), what, self.inbox_path)] +
                      text.listed(["  " + relpath for relpath in relpaths], filescreen.MAX_FILES_LISTED),
                      dryrun.label(), 'red')

    def _target(self, relpath):
        """Where Claude recommends the inbox's file at relpath go, in the sorted tree"""
        return ai.recommended_path(self._recommendations[relpath])

    def _transfer(self, moves, is_move):
        """Copy the inbox's files to the sorted tree, of another kind, each of moves (relpath in the
        inbox's tree, relpath in the sorted tree's): an upload to Drive, or a download from it, as a
        sync's copy does; then if is_move, remove from the inbox the ones copied. Returns the moves
        done (none in a dry run)."""
        source_of = {new_relpath: relpath for relpath, new_relpath in moves}
        files = [entries.FileEntry(os.path.basename(new_relpath), new_relpath,
                                   os.path.join(self.inbox_path, relpath))
                 for relpath, new_relpath in moves]
        source = None if self.root_is_cloud else _Renamed(self._inbox_tree, source_of)
        # (Each uploaded from its own path in the inbox, not from its relpath in the sorted tree)
        self._root_tree.copy_in(files, source)
        if dryrun.DRYRUN:
            if is_move:
                self._inbox_tree.remove_files(self._entries(relpath for relpath, _ in moves))
            return []
        done = [(relpath, new_relpath) for relpath, new_relpath in moves if self._root_tree.has_file(new_relpath)]
        if is_move and done:
            self._inbox_tree.remove_files(self._entries(relpath for relpath, _ in done))
            done = [(relpath, new_relpath) for relpath, new_relpath in done
                    if not self._inbox_tree.has_file(relpath)]
        return done

    def log_trees(self):
        """[(tree, path)] of the sorted tree, a tree of its own (as it is now: a Drive one from the
        cache), to read and write its log (see replicalog.py); an inbox has none"""
        return [(_tree(self.root_path), self.root_path)]

    def _entries(self, relpaths):
        """The entries of the inbox's files at relpaths (in its tree), to remove them"""
        found = []
        for relpath in relpaths:
            node = self._inbox_tree.get_node(relpath)
            found.append(node.data if node is not None else entries.FileEntry(
                os.path.basename(relpath), relpath, os.path.join(self._inbox_tree.fullpath(), relpath)))
        return found

    def _remove(self, relpaths, listed=None, to_trash=False):
        """Remove the inbox's files at relpaths, once the user confirms twice; listed: the lines that
        list them (else their relpaths). With to_trash, a local inbox's go to the desktop's trash
        (Drive's go to its trash anyway), rather than for good."""
        lines = ["Remove %s from %s?" % (_files(len(relpaths)), self.inbox_path)]
        listed = listed or ["  %s" % (relpath,) for relpath in relpaths]
        lines += text.listed(listed, filescreen.MAX_FILES_LISTED)
        if dryrun.DRYRUN:
            lines.append(dryrun.NOTE)
        if not self._said_yes(lines, LABEL):
            return None
        if not self._is_sure(len(relpaths), self.inbox_path, self.inbox_is_cloud, to_trash, LABEL):
            return None
        file_entries = self._entries(relpath for relpath in relpaths)
        # Once it's done (or stopped), Enter goes back to the picker, so what was removed can be read
        with messages.progress_screen("Removing %s from %s%s" % (_files(len(relpaths)), self.inbox_path,
                                                                " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock, \
                (self._inbox_tree.trashing() if to_trash and not self.inbox_is_cloud else contextlib.nullcontext()):
            self._inbox_tree.remove_files(file_entries)
        if dryrun.DRYRUN:
            return relpaths
        left = set(self._inbox_files())
        kept = [relpath for relpath in relpaths if relpath in left]
        if kept:
            self._say_not_done("removed", kept, len(relpaths))
        removed = [relpath for relpath in relpaths if relpath not in left]
        return removed


class _Renamed(object):
    """A tree to copy from (a copy_in() source) whose files are asked for by
    where they go (relpaths in the tree copied into), each where source_of says it is in tree"""
    def __init__(self, tree, source_of):
        self._tree = tree
        self._source_of = source_of

    def cant_fetch(self, relpath):
        return self._tree.cant_fetch(self._source_of[relpath])

    def fetch_file(self, relpath, local_path):
        self._tree.fetch_file(self._source_of[relpath], local_path)


def _tree(path):
    """The tree of a replica path on its own: a Drive folder's (from the cache), or a local dir's
    (not scanned)"""
    if paths.is_cloud_path(path):
        return clouddirtree.factory(path)
    return localdiskdirtree.LocalReplica(path)


# One way for all (see paths.normalized())
_normalized = paths.normalized


def run(inbox_path, root_path, known_replicas=None):
    """Sort the inbox at inbox_path into root_path (see InboxSort), with known_replicas (a
    replicas.Replicas, saved) remembering them as a recent sort, and what's known of each (its log,
    see replicalog.py); once it's done, offer an entry for the sorted tree's log, if it changed
    (an inbox has no log)"""
    # A Drive sorted tree's file list is kept in it too, as it changes (see drivemeta.py): the copy
    # there is checked before its tree is made
    with drivemeta.kept([(root_path, None)]):
        _run(inbox_path, root_path, known_replicas)


def _run(inbox_path, root_path, known_replicas):
    sort = InboxSort(inbox_path, root_path, known_replicas)
    if known_replicas is not None:
        known_replicas.record_sort(sort.inbox_path, sort.root_path)
        replicalog.note_seen(sort.log_trees(), known_replicas)
        replicas.save(known_replicas)
    names = replicanames.short_names([sort.inbox_path, sort.root_path])
    with picker.place("Sort %s \u2192 %s" % (names[sort.inbox_path], names[sort.root_path])):
        if not sort.prepare_hashing():
            return
        sort.run()
    if known_replicas is not None:
        replicalog.offer_entries(sort.changes, sort.log_trees(), known_replicas)


def _fitting(parts, width):
    """parts (a path's, [(text, origin)]) to fit in width columns: the first one (the sorted tree's
    root) cut to its last dir, after '.../', if they don't"""
    if sum(picker.display_width(text) for text, _ in parts) <= width or not parts:
        return parts
    first, origin = parts[0]
    return [('.../' + os.path.basename(first.rstrip('/')) + '/', origin)] + parts[1:]


def _bracket(names, width):
    """A bracket width columns wide, saying the first of names (the longest first) that fits, e.g.
    [Claude's dir ]; or as much of the last as fits"""
    if width < 2:
        return ' ' * width
    inside = next((name for name in names if len(name) <= width - 2), names[-1][:width - 2])
    return '[' + inside + ' ' * (width - 2 - len(inside)) + ']'


# The phrases of the action menu's options that say where the files go, each in its source's color
# (as the brackets below the menu: see CLAUDES_DIR), the longest first
_PHRASE_COLORS = [("Claude's recommendations", CLAUDES_DIR[0]), ("Claude's recommendation", CLAUDES_DIR[0]),
                  ("under Claude's names", CLAUDES_NAME[0]), ("under Claude's name", CLAUDES_NAME[0]),
                  ("Claude's dir", CLAUDES_DIR[0]), ("a dir you pick", YOUR_DIR[0]),
                  ("under a name you type", YOUR_NAME[0]), ("keeping its name", OWN_NAME[0]),
                  ("keeping their name", OWN_NAME[0])]


def _option_text(label, color, parts=()):
    """An action menu option's label as it's shown, in styled parts: in color, but the phrases
    saying where the files go (_PHRASE_COLORS) and the destination's parts at its end (parts:
    [(text, (color, names))], see SORTED_TREE) in their sources' colors (the sorted tree's plain)"""
    joined = ''.join(text for text, _ in parts)
    head, ending = (label[:-len(joined)], list(parts)) if joined and label.endswith(joined) else (label, [])
    pattern = '(%s)' % ('|'.join(re.escape(phrase) for phrase, _ in _PHRASE_COLORS),)
    phrase_colors = dict(_PHRASE_COLORS)
    pieces = [(piece, phrase_colors.get(piece, color)) for piece in re.split(pattern, head)]
    return picker.styled(pieces + [(text, source_color) for text, (source_color, _) in ending])


def _title(text, color):
    """A preview's title, bold in color"""
    return picker.styled([(text, 'bold,' + color)])


def _grey(text):
    """A preview's line of how it's going (rather than what's known)"""
    return picker.styled([(text, 'grey')])


def _wrapped(text, indent):
    return [indent + line for line in textwrap.wrap(text, PREVIEW_WIDTH - len(indent))] if text else []


def _wrapped_path(path, indent):
    """A path's lines in the preview column: cut at its spaces, or where it fills a line (not at its
    names' hyphens)"""
    return [indent + line for line in textwrap.wrap(path, PREVIEW_WIDTH - len(indent), break_on_hyphens=False)]


def _relpath(path, root):
    relpath = os.path.relpath(path, root)
    return '' if relpath == '.' else relpath


# One answer for all (see paths.is_at_or_under()): the root has all
_is_at_or_under = paths.is_at_or_under


