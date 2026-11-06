"""The sort of an inbox into a sorted tree (see dirdelta.inbox): InboxSort, one object whose
parts are mixins, each in a module of its own, and run(), which runs one"""
import os
import threading

from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from dirdelta.drive import drivemeta
from dirdelta.inbox.actions.approval import Approval
from dirdelta.inbox.ai.ask_ai import AskAI
from dirdelta.inbox.ai.claude import Claude
from dirdelta.inbox.ai.claude_dirs import ClaudeDirs
from dirdelta.inbox.ai.claude_files import ClaudeFiles
from dirdelta.inbox.copies import Copies
from dirdelta.inbox.actions.destinations import Destinations
from dirdelta.inbox.actions.dirs import Dirs
from dirdelta.inbox.keys import Keys
from dirdelta.inbox.listing import Listing, _normalized, _tree
from dirdelta.inbox.actions.menu import Menu
from dirdelta.inbox.previews import Previews
from dirdelta.inbox.screen import Screen
from dirdelta.inbox.side import Side
from dirdelta.inbox.actions.transfer import Transfer
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.matching import elsewhere
from dirdelta.screens import aiplan_screen
from dirdelta.screens import archive_screen
from dirdelta.trees import paths
from dirdelta.ui import filescreen
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.ui import sidetree
from dirdelta.known import log_entries


class InboxError(Exception):
    pass


class InboxSort(Listing, Screen, Keys, Side, Previews, Copies, Menu, Destinations,
                Claude, ClaudeDirs, ClaudeFiles, Dirs, AskAI, Approval, Transfer,
                filescreen.FilesScreen):

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
    # A dir's files, all picked: Claude's say of the dir as a whole, and moving or removing it whole
    ASK_DIR = 'ask about the dir'
    MOVE_DIR = "move the dir to Claude's"
    MOVE_DIR_TO = 'move the dir to'
    REMOVE_DIR = 'remove the dir'
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
        self.changes = log_entries.Changes()
        self._check_paths()
        self._make_trees()
        self._init_claude()
        # One at a time: what the describer and the opener download (they'd write the same .part, see
        # downloads.get()), and what the screen changes in the trees, which those read. It isn't for
        # Drive's connection: each thread has its own (driveapi.service()).
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
        # What the last listing of the inbox found (see _inbox_files())
        self._listing = {}
        # The sorted tree's dirs and files, for the tree beside the picker
        self._side_listing = sidetree.Listing(self.root_path, self._root_tree, self._inbox_in_root)

    def _check_paths(self):
        """Check the inbox's and the sorted tree's paths (making the Drive cache, if one's on Drive and
        there's none), and whether a move is a rename; raises InboxError if they can't be sorted"""
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

    def _make_trees(self):
        """The inbox's and the sorted tree's trees, neither removed when it's left empty, nor moved whole"""
        self._inbox_tree, self._root_tree = _tree(self.inbox_path), _tree(self.root_path)
        self._inbox_tree.keep_dirs([''])
        self._root_tree.keep_dirs(['' if self._inbox_in_root is None else self._inbox_in_root])


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
        log_entries.note_seen(sort.log_trees(), known_replicas)
        replicas.save(known_replicas)
    names = replicanames.short_names([sort.inbox_path, sort.root_path])
    with picker.place("Sort %s \u2192 %s" % (names[sort.inbox_path], names[sort.root_path])):
        if not sort.prepare_hashing():
            return
        sort.run()
    if known_replicas is not None:
        log_entries.offer_entries(sort.changes, sort.log_trees(), known_replicas)
