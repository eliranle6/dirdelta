"""What pickers are given and give back: their options' kinds, and what a pick returns"""
import collections


# What shown_as (see pick_option()) shows an option as when it can't be picked: in grey, with Enter
# doing nothing on it
Disabled = collections.namedtuple('Disabled', ['text'])
# What shown_as shows an option as when it's not one at all (a heading, a blank line, a line of
# information): as a Disabled, and skipped when moving through the menu
Skipped = collections.namedtuple('Skipped', ['text'])
# What shown_as shows an option as in a color (a text color: red, green, yellow, blue, magenta, cyan)
Colored = collections.namedtuple('Colored', ['text', 'color'])
# An option of a menu that's more than its text (pick_option()'s options may be plain strings too):
# what's returned when it's picked (any hashable value), its label (its plain text, e.g. what it's
# found by when searching), and how it's shown at first, if otherwise (a string, or one of the above)
Option = collections.namedtuple('Option', ['id', 'label', 'shown'], defaults=(None,))
# A line of a menu that isn't an option at all is a Skipped in pick_option()'s options, and this one a
# blank line between its sections
BLANK = Skipped('')


# What pick_files() returns: the key that ended picking ('' for Enter), the selected node's relpath
# ('' for the root), to show it again there, and the files picked
# (After Enter or another of its keys in the side tree, side_pressed says which: '' for Enter)
Picked = collections.namedtuple('Picked', ['key', 'selected', 'files', 'side_selected', 'side_pressed'],
                                defaults=(None, ''))

# Another tree beside a pick_files() picker's, in the lower part of its right column, to look
# through (Ctrl-L moves in it, Ctrl-H back), e.g. where its files would go: its root's name, its
# items ('d DIR' or 'f FILE', relpaths in it, each dir before what's in it), whether Enter there
# ends picking (then the Picked's key is SIDE_KEY, and its side_selected the side tree's selected
# relpath, '' the root), and follow, if given: called with the picker's selected relpath each time
# it moves (on a thread of its own), returning the side tree's relpath to select (or its closest
# dir there), or None to leave it where it is; keys: other keys that end picking there, as Enter;
# key_hints: the keys row while moving in it ([(key, what it does)]); start: start moving in it, on
# this relpath or its closest dir there ('' its root), rather than in the tree it's beside (None)
Side = collections.namedtuple('Side', ['root_name', 'items', 'is_enter_picking', 'follow', 'keys', 'key_hints', 'start'],
                              defaults=(False, None, '', (), None))
# What a Picked's key is when Enter in the side tree ended it (a byte no key prints)
SIDE_KEY = '\x1d'
