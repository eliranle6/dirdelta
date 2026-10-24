"""dirdelta's messages, printed as plain lines between pickers (each picker has the terminal while
it's open).

A picker covers what was printed before it, so the lines printed since the last picker are also
kept, for the next picker to show (see take_recent()).
"""
import contextlib
import shutil
import sys

import termcolor

# How many of the lines printed since the last picker are kept for the next one
MAX_RECENT_LINES = 12

_recent_lines = []
_nr_recent_lines_dropped = 0
# Whether the action on the progress screen was stopped (Ctrl-C)
_is_stopped = False


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


def note_stopped():
    """Say that an action was stopped with Ctrl-C (also on the progress screen's top line), e.g. by an
    action that catches it to say how far it got."""
    global _is_stopped
    _is_stopped = True
    print_line("Stopped (Ctrl-C)", "red")


# A label's look on a terminal, by its color name: bold, black or white on the color
_LABEL_STYLES = {'green': '\033[1;30;42m', 'red': '\033[1;37;41m'}


@contextlib.contextmanager
def progress_screen(title, label=None):
    """Show what's printed inside (an action's progress) on the whole screen, under title, which
    stays on the top line while the lines scroll under it. When the action ends, wait for Enter, so
    its report can be read before the next picker covers it.

    Ctrl-C inside stops the action (which may catch it itself, to say how far it got). label, a
    (text, color) pair (e.g. dryrun.label()), starts the top line. Without a terminal, the title and
    the lines are just printed.
    """
    global _is_stopped
    _is_stopped = False
    is_terminal = sys.stdout.isatty() and sys.stdin.isatty()
    if not is_terminal:
        print_line(title if label is None else "%s: %s" % (label[0], title))
        try:
            yield
        except KeyboardInterrupt:
            note_stopped()
        return

    height = shutil.get_terminal_size().lines
    # Clear the screen, title on the top line, and the lines scrolling in the rest (a scroll region)
    _write("\033[2J\033[H" + _top_line("Ctrl-C to stop: " + title, label) +
           "\033[2;%dr\033[2;1H" % (height,))
    try:
        yield
    except KeyboardInterrupt:
        note_stopped()
    finally:
        done = "Stopped" if _is_stopped else "Done"
        # Save the cursor, rewrite the top line, and restore it. What to do first, in case the line
        # is cut.
        _write("\0337\033[1;1H" + _top_line("%s. Press Enter to continue: %s" % (done, title), label) +
               "\0338")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        # Back to scrolling the whole screen
        _write("\033[r")
        # The report was read here, so the next picker needn't show it again
        take_recent()


def _top_line(text, label=None):
    """text on the current line, in reverse video, over the whole width, after label (text, color)
    in its color"""
    width = shutil.get_terminal_size().columns
    line = ""
    if label is not None:
        label_text = " %s " % (label[0],)
        line = _LABEL_STYLES.get(label[1], "\033[1m") + label_text + "\033[0m "
        width -= len(label_text) + 1
    return line + "\033[7m" + text[:max(0, width)].ljust(max(0, width)) + "\033[0m\033[K"


def _write(text):
    sys.stdout.write(text)
    sys.stdout.flush()

