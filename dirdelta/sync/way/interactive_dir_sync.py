"""A way of a sync: the files in src that aren't in dst (and the ones both have that differ),
picked and copied, removed or renamed, again and again (see InteractiveDirSync). Its parts are
mixins, each in a module of its own here."""
from dirdelta.drive import clouddirtree
from dirdelta.matching import elsewhere
from dirdelta.screens import aiplan_screen
from dirdelta.screens import archive_screen
from dirdelta.sync.way.ask_ai import AskAI
from dirdelta.sync.way.browsing import Browsing
from dirdelta.sync.way.copying import Copying
from dirdelta.sync.way.keys import Keys
from dirdelta.sync.way.lists import Lists
from dirdelta.sync.way.menu import Menu
from dirdelta.sync.way.renames import Renames
from dirdelta.ui import filescreen
from dirdelta.ui import opening
from dirdelta.ui import sidetree


class InteractiveDirSync(Browsing, Keys, Lists, Menu, Copying, AskAI, Renames,
                         filescreen.FilesScreen):

    """The files in src that aren't in dst, which the user picks and then copies to dst, removes
    from src, or renames to match where the other replica has them (see elsewhere.py), again and
    again, until they're done. With them, the files both have at the same paths that differ
    (differing.py), tagged: Copy replaces dst's version of one, Copy back src's."""
    COPY = 'copy'
    # Copying dst's versions of picked files that differ to src, replacing src's
    COPY_BACK = 'copy back'
    REMOVE = 'remove'
    # Moving dst's files of the same names to the picked files' paths, or the picked files to
    # theirs
    RENAME_IN_DST = 'rename in dst'
    RENAME_IN_SRC = 'rename in src'
    # What the picker's keys do on the selected file, in the menu too: opening it (Ctrl-X), reading
    # its folder anew from Drive (r)
    OPEN = 'open'
    READ_ANEW = 'read anew'
    ASK_AI = 'ask AI'
    EXPLORE = 'explore'
    # The picker's keys that do an option of the menu, shown before it
    # (Ctrl-X opens the selected one, not the picked ones: Open has no key)
    SHORTCUTS = {READ_ANEW: 'Ctrl-R', ASK_AI: aiplan_screen.KEY_NAME, EXPLORE: archive_screen.KEY_NAME}
    # The label of each action's confirmation, so what it's for shows at a glance (magenta, not
    # red: red is LIVE's)
    LABELS = {COPY: ('COPY', 'blue'), COPY_BACK: ('COPY', 'blue'), REMOVE: ('REMOVE', 'magenta'),
              RENAME_IN_DST: ('RENAME', 'cyan'), RENAME_IN_SRC: ('RENAME', 'cyan')}

    # The action menu's first option, so it's the one selected at first: doing nothing
    NOTHING = "Nothing: back to the files"
    # The key that removes what's selected in the tree beside the picker (dst's)
    SIDE_REMOVE_KEY = 'd'

    def __init__(self, src, dst, missing=None, src_index=None, dst_index=None, checked=None, changes=None,
                 differs=None, only_differing=False, compared=None):
        """missing: a future (concurrent.futures.Future) of find_missing(src, dst), e.g. found in
        the background, to use rather than finding it again; differs, likewise, of
        differing.find(src, dst). With only_differing, only the files that differ are shown. src_index, dst_index: the replicas'
        elsewhere.Index, kept by the caller so they're built once, and kept up to date here.
        checked: which of src's files' matches have the same contents (see
        elsewhere.check_contents()), kept by the caller too, so each is compared once. compared: the
        files of the same size compared on request (see differing.find()), kept by the caller."""
        self._src = src
        self._dst = dst
        self._missing_future = missing
        self._differs_future = differs
        self._only_differing = only_differing
        self._compared = compared
        # The files shown that differ ({relpath: differing.Change}), as of the last diff
        self.differs = {}
        self.src_index = src_index or elsewhere.Index(src)
        self.dst_index = dst_index or elsewhere.Index(dst)
        # The action menu's last action done (see browse())
        self._last_action = None
        self.checked = checked if checked is not None else {}
        # Where what's changed live is noted (a log_entries.Changes, by the replicas' displaynames),
        # for the entries of their logs, if anywhere
        self.changes = changes
        # Whether the replicas' files changed here (copied, removed, moved, or read anew from
        # Drive), so what each lacks may have
        self.has_changed = False
        # Whether a replica was read anew: what's known of its files' contents may be wrong, also
        # the other way's (dirsync_main)
        self.was_read_anew = False
        # Opens src's files (Ctrl-X, or Open in the action menu)
        self._opener = opening.Opener(src)
        # What the AI was last asked (see _ask_ai()), to start from next time
        self._last_instruction = ''
        # dst's dirs and files, for the tree beside the picker
        self._side_listing = sidetree.Listing(
            dst.displayname() if isinstance(dst, clouddirtree.CloudDirTree) else dst.fullpath(), dst)

    def browse(self):
        """See _browse(); what it kept of dst is let go after"""
        try:
            self._browse()
        finally:
            self._side_listing.close()
