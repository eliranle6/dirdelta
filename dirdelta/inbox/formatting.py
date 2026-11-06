"""Small helpers for the sort's texts: counts, the action menu's options and the
preview column's lines"""
import os
import re
import textwrap

from dirdelta.inbox.constants import CLAUDES_DIR, CLAUDES_NAME, OWN_NAME, PREVIEW_WIDTH, YOUR_DIR, YOUR_NAME
from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.util import text


files_text = text.files


def of_picked(count, total):
    """How many of the picked files (total) count is: 'the 3 files' when it's all of them, else '3 of
    the 5 files'"""
    if count == total:
        return "the " + files_text(count)
    return "%d of the %s" % (count, files_text(total))


join_path = paths.join


class Action(object):
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


def fitting(parts, width):
    """parts (a path's, [(text, origin)]) to fit in width columns: the first one (the sorted tree's
    root) cut to its last dir, after '.../', if they don't"""
    if sum(picker.display_width(text) for text, _ in parts) <= width or not parts:
        return parts
    first, origin = parts[0]
    return [('.../' + os.path.basename(first.rstrip('/')) + '/', origin)] + parts[1:]


def bracket(names, width):
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


def option_text(label, color, parts=()):
    """An action menu option's label as it's shown, in styled parts: in color, but the phrases
    saying where the files go (_PHRASE_COLORS) and the destination's parts at its end (parts:
    [(text, (color, names))], see SORTED_TREE) in their sources' colors (the sorted tree's plain)"""
    joined = ''.join(text for text, _ in parts)
    head, ending = (label[:-len(joined)], list(parts)) if joined and label.endswith(joined) else (label, [])
    pattern = '(%s)' % ('|'.join(re.escape(phrase) for phrase, _ in _PHRASE_COLORS),)
    phrase_colors = dict(_PHRASE_COLORS)
    pieces = [(piece, phrase_colors.get(piece, color)) for piece in re.split(pattern, head)]
    return picker.styled(pieces + [(text, source_color) for text, (source_color, _) in ending])


def preview_title(text, color):
    """A preview's title, bold in color"""
    return picker.styled([(text, 'bold,' + color)])


def grey_line(text):
    """A preview's line of how it's going (rather than what's known)"""
    return picker.styled([(text, 'grey')])


def wrapped(text, indent):
    return [indent + line for line in textwrap.wrap(text, PREVIEW_WIDTH - len(indent))] if text else []


def wrapped_path(path, indent):
    """A path's lines in the preview column: cut at its spaces, or where it fills a line (not at its
    names' hyphens)"""
    return [indent + line for line in textwrap.wrap(path, PREVIEW_WIDTH - len(indent), break_on_hyphens=False)]


def relpath_in(path, root):
    relpath = os.path.relpath(path, root)
    return '' if relpath == '.' else relpath


# One answer for all (see paths.is_at_or_under()): the root has all
is_at_or_under = paths.is_at_or_under


def dirs_text(count):
    return "%d dir%s" % (count, "" if count == 1 else "s")


def spread(items, count):
    """count of items (all, if there are no more), spread over them: the first, the last, and evenly
    between, in their order"""
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[0]]
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def path_of(*parts):
    """A destination's path, of its parts ([(text, origin)], see SORTED_TREE)"""
    return ''.join(text for text, _ in parts)
