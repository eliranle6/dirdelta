"""Text in styles and colors, as treepicker shows it: styled(), segments(), highlighted()"""
import re
import unicodedata

from dirdelta.ui.picker.kinds import BLANK


HIGHLIGHT_MARK = '\x01'


def segments(parts):
    """A text in colored parts, for treepicker's labels' markup (a status for shown_as's '', a line of
    pick_option(previews_below=...)'s): parts is [(text, color)], a --label-color, or plain for None
    or ''; each after HIGHLIGHT_MARK, its color, HIGHLIGHT_MARK; the empty ones left out. The one
    way it's made."""
    return ''.join('%s%s%s%s' % (HIGHLIGHT_MARK, color or '', HIGHLIGHT_MARK, text) for text, color in parts if text)


def highlighted(text, color='green'):
    """A pick_files() preview's line, shown bold on color (a --label-color), across the column"""
    return segments([(text, color)])


# A text of a tree's node (shown_as's) or of a preview's line is in styled parts with it (see
# styled())
STYLE_MARK = '\x02'
# The styles' colors there (text colors, rather than labels' backgrounds)
STYLE_COLORS = ('red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'grey', 'orange')


def styled(parts):
    """A pick_files() node's text (shown_as's), or a preview column's line, in styled parts: parts is
    [(text, style)], a style being a STYLE_COLORS color, 'bold', or both ('bold,magenta'; None or
    '': plain). A node's styles show while it isn't selected, picked or matching a search (which
    matches its text, not its styles); the empty parts are left out."""
    if not any(style for text, style in parts if text):
        return ''.join(text for text, _ in parts)
    return ''.join('%s%s%s%s' % (STYLE_MARK, style or '', STYLE_MARK, text) for text, style in parts if text)


def grouped(groups):
    """A menu's options of groups (lists of options, e.g. of similar actions), with a blank line
    between each two (the empty groups left out)"""
    options = []
    for group in groups:
        if group:
            options += ([BLANK] if options else []) + list(group)
    return options


def shortcut_prefixes(labels, shortcuts):
    """{label: what a menu's option is shown after}: its key's name in brackets, bold (shortcuts:
    {label: the key's name, e.g. 'Ctrl-X'}, for the options a picker's key does too), or as many
    spaces, so the options' texts line up; all '' when none has a key"""
    width = max([display_width(key) + 3 for key in shortcuts.values()] or [0])
    return {label: (styled([("[%s]" % (shortcuts[label],), 'bold'), (" " * (width - display_width(shortcuts[label]) - 2), None)])
                    if label in shortcuts else " " * width)
            for label in labels}


def unstyled(text):
    """text (styled()'s) without its styles"""
    return re.sub('%s[^%s]*%s' % ((STYLE_MARK,) * 3), '', text)


def display_width(text):
    """How many columns text takes on a terminal (a wide character, e.g. CJK, two; a combining one
    none)"""
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in 'WF' else 1
               for char in text)
