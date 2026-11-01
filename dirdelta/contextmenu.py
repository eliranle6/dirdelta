"""The file pickers' menu for when nothing's picked (:), of what can be done there with the selected
file or dir, each with its key, and below them the keys that only work in the picker itself. Each
caller says what's offered (Entry); what's chosen comes back for it to do, as if its key was pressed."""
import collections

from dirdelta import picker
from dirdelta import text

# The file pickers' key: with files picked, it's Enter's menu of what to do with them
KEY = ':'
KEY_HINT = (KEY, 'menu')
# What the Entries of Space and of Enter's menu come back as (the others: their keys, see below)
PICK = 'pick'
WHAT_TO_DO = 'what to do'
NOTHING = "Nothing: back to the files"
IN_THE_PICKER = "These keys work in the file list itself:"
# What only treepicker does, so can't be done from a menu
PICKER_KEYS = [('V', 'pick a range'), ('/', 'search'), ('f', 'only the matches of a search, or all'),
               ('p', 'show or hide the preview column'), ('?', 'all the keys')]
SIDE_KEY_NAME = 'Ctrl-W l'

# An option: its key's name (None: it has none), what it does, and what's returned if it's chosen
Entry = collections.namedtuple('Entry', ['key_name', 'label', 'result'])


def selected_name(selected):
    """What to call the picker's selected relpath in a menu"""
    return selected or "all the files"


def under(relpaths, selected):
    """Those of relpaths that the selected relpath is, or has ('' has all)"""
    prefix = selected + '/' if selected else ''
    return [relpath for relpath in relpaths if relpath == selected or relpath.startswith(prefix)]


def choose(entries, header, label=None, side=None):
    """Let the user choose one of entries, below which the picker's own keys are shown (with side, what
    the tree beside the picker is, its key's too). Returns its result, or None to go back."""
    keys = list(PICKER_KEYS) + ([(SIDE_KEY_NAME, 'move to %s, on the right (Ctrl-W h: back)' % (side,))] if side else [])
    results = {entry.label: entry.result for entry in entries}
    # The keys' lines are options too, though they can't be chosen, so each is unique
    lines = ["%s %s" % key for key in keys]
    labels, blanks = picker.grouped([[NOTHING], list(results), [IN_THE_PICKER] + lines])
    shortcuts = {entry.label: entry.key_name for entry in entries if entry.key_name}
    shortcuts.update({line: key for line, (key, _) in zip(lines, keys)})
    prefixes = picker.shortcut_prefixes([NOTHING, IN_THE_PICKER] + list(results) + lines, shortcuts)
    shown = dict(blanks)
    shown[NOTHING] = prefixes[NOTHING] + NOTHING
    for option in results:
        shown[option] = prefixes[option] + option
    shown[IN_THE_PICKER] = picker.Skipped(IN_THE_PICKER)
    for line, (_, what) in zip(lines, keys):
        shown[line] = picker.Skipped(prefixes[line] + what)
    answer = picker.pick_option(labels, header=header, shown_as=lambda: shown, label=label, title="Menu")
    return results.get(answer)


def nothing_picked(count):
    return "Nothing's picked (of %s). What to do?" % (text.files(count),)
