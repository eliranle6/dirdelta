"""dirdelta's messages, printed as plain lines between pickers (each picker has the terminal while
it's open)."""
import sys

import termcolor


def print_line(line, color=None):
    """Print line (in color, a termcolor name like 'red', if given)."""
    if color is not None:
        line = termcolor.colored(line, color)
    # surrogateescape: lines may hold file names that aren't valid UTF-8
    sys.stdout.buffer.write((line + '\n').encode('utf-8', 'surrogateescape'))
    sys.stdout.flush()
