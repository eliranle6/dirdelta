"""dirdelta's messages, printed as plain lines between pickers (each picker has the terminal while
it's open).

A picker covers what was printed before it, so the lines printed since the last picker are also
kept, for the next picker to show (see take_recent()).
"""
import sys

import termcolor

# How many of the lines printed since the last picker are kept for the next one
MAX_RECENT_LINES = 8

_recent_lines = []
_nr_recent_lines_dropped = 0


def print_line(line, color=None):
    """Print line (in color, a termcolor name like 'red', if given)."""
    global _nr_recent_lines_dropped
    _recent_lines.append(line)
    if len(_recent_lines) > MAX_RECENT_LINES:
        del _recent_lines[0]
        _nr_recent_lines_dropped += 1
    if color is not None:
        line = termcolor.colored(line, color)
    # surrogateescape: lines may hold file names that aren't valid UTF-8
    sys.stdout.buffer.write((line + '\n').encode('utf-8', 'surrogateescape'))
    sys.stdout.flush()


def take_recent():
    """The lines printed since the last call (the last MAX_RECENT_LINES of them, after a line saying
    how many earlier ones there were, if any), and forget them."""
    global _nr_recent_lines_dropped
    lines = list(_recent_lines)
    if _nr_recent_lines_dropped:
        lines.insert(0, '(%d earlier lines)' % (_nr_recent_lines_dropped,))
    del _recent_lines[:]
    _nr_recent_lines_dropped = 0
    return lines
