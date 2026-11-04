"""What the two file screens have in common, the sync's (interactive_dir_sync.py) and the inbox's
(inbox.py): a picker of files, whose keys and menus do much the same, and what's confirmed before
files are removed. Each has its own loop: what's done after an action differs (a sync's files are
what the other replica lacks, an inbox's are what's left in it)."""
import os

from dirdelta import archive_screen
from dirdelta import contextmenu
from dirdelta import hashes_screen
from dirdelta import picker
from dirdelta import text

CONFIRM_NO = 'No'
CONFIRM_YES = 'Yes'
# A removal is confirmed again, with this, so a second Enter on Yes doesn't do it
CONFIRM_SURE = 'Yes, remove them'
# How many files a confirmation lists (then how many more there are)
MAX_FILES_LISTED = 5
# Ctrl-R
REFRESH_KEY = '\x12'
REFRESH_KEY_NAME = 'Ctrl-R'
# What it does in the tree beside the picker, by whether that's on Drive
SIDE_REFRESH_HINTS = {True: 'read this folder anew from Drive', False: 'see what changed in it'}


class _ReadAnew(object):
    """What an action menu returns (rather than the files done) for reading a folder anew from Drive,
    as REFRESH_KEY does"""


READ_ANEW = _ReadAnew()


class FilesScreen(object):
    CONFIRM_NO, CONFIRM_YES, CONFIRM_SURE = CONFIRM_NO, CONFIRM_YES, CONFIRM_SURE
    MAX_FILES_LISTED = MAX_FILES_LISTED
    REFRESH_KEY, REFRESH_KEY_NAME = REFRESH_KEY, REFRESH_KEY_NAME

    def _context_menu(self, selected, files):
        """What to do with nothing picked, on the selected relpath: see contextmenu.py"""
        raise NotImplementedError()

    def _menu_key(self, answer, selected, files):
        """Do what the context menu's answer says, if it's one of this screen's own keys that stay in
        the picker. Returns whether it was."""
        return False

    def _explore(self, relpath, files):
        raise NotImplementedError()

    def _dashboard(self):
        raise NotImplementedError()

    def _shared_key(self, chosen, files):
        """What's the same for the keys of a pick_files() of files: the context menu (standing for
        another key, or for Enter), exploring a zip and the dashboard. Returns (chosen, None), chosen
        as the key the context menu said, if it's left to the caller, or else (None, what to pick when
        the picker's shown again)."""
        selected = chosen.selected
        if chosen.key == contextmenu.KEY:
            # With files picked, Enter's menu of them; else one of what the keys do
            answer = '' if chosen.files else self._context_menu(selected, files)
            if answer is None:
                return None, chosen.files
            if answer == contextmenu.PICK:
                return None, contextmenu.under(files, selected)
            if self._menu_key(answer, selected, files):
                return None, chosen.files
            chosen = chosen._replace(key='' if answer == contextmenu.WHAT_TO_DO else answer,
                                     files=contextmenu.under(files, selected)
                                     if answer == contextmenu.WHAT_TO_DO else chosen.files)
        if chosen.key == archive_screen.KEY:
            self._explore(selected, files)
            return None, chosen.files
        if chosen.key == hashes_screen.KEY:
            self._dashboard()
            return None, chosen.files
        return chosen, None

    def _said_yes(self, lines, label):
        """Whether the user says yes to the question of lines"""
        return picker.pick_option([CONFIRM_NO, CONFIRM_YES], header='\n'.join(lines), title="Sure?",
                                  label=label) == CONFIRM_YES

    def _is_sure(self, count, where, is_drive, to_trash, label):
        """Whether the user is sure of removing count files from where (asked after _said_yes()):
        Drive's go to its trash, a local one's to the desktop's (to_trash), or for good"""
        sure = "Are you sure? %s will be removed from %s%s." % (
            text.files(count), where, " (to Drive's trash)" if is_drive else
            " (to the trash)" if to_trash else ", for good")
        return picker.pick_option([CONFIRM_NO, CONFIRM_SURE], header=sure, label=label, title="Sure?") == CONFIRM_SURE


def shown_near(relpath, missing, before=None):
    """relpath (a picker's selection), if the picker of missing (files) still shows it; else the
    closest file to where it was among before (the files shown then, in their order): the next
    one still shown, or the one before, whichever is in a closer dir (the next, of two as close); or
    else the closest dir above it still shown ('' the root)"""
    if before and not _is_shown(relpath, missing):
        prefix = relpath + '/' if relpath else ''
        # Where it was: its place, or a dir's first file's
        place = next((index for index, path in enumerate(before) if path == relpath or path.startswith(prefix)), None)
        if place is not None:
            left = set(missing)
            after = next((path for path in before[place:] if path in left), None)
            earlier = next((path for path in reversed(before[:place]) if path in left), None)
            found = [path for path in (after, earlier) if path is not None]
            if found:
                return max(found, key=lambda path: _common_depth(path, relpath) * 2 + (path == after))
    while relpath:
        prefix = relpath + '/'
        if any(path == relpath or path.startswith(prefix) for path in missing):
            return relpath
        relpath = os.path.dirname(relpath)
    return relpath


def _is_shown(relpath, missing):
    """Whether the picker of missing (files) shows relpath: one of them, or a dir of some"""
    prefix = relpath + '/'
    return not relpath or any(path == relpath or path.startswith(prefix) for path in missing)


def _common_depth(relpath, other):
    """How many dirs the two relpaths are both in"""
    depth = 0
    for part, other_part in zip(relpath.split('/')[:-1], other.split('/')[:-1]):
        if part != other_part:
            break
        depth += 1
    return depth
