"""dirdelta's messages: plain lines, printed between pickers (each picker has the terminal while it's
open), and screens, which show lines until Enter is pressed: progress_screen() for an action's
progress, show() for messages to read before the next picker covers them.
"""
import contextlib
import shutil
import sys

import termcolor

# Whether the action on the progress screen was stopped (Ctrl-C)
_is_stopped = False
# Whether the last line printed is print_progress()'s, so it hasn't ended
_is_progress_shown = False


def print_line(line, color=None):
    """Print line (in color, a termcolor name like 'red', if given)."""
    global _is_progress_shown
    if color is not None:
        line = termcolor.colored(line, color)
    if _is_progress_shown:
        line = '\n' + line
        _is_progress_shown = False
    # surrogateescape: lines may hold file names that aren't valid UTF-8
    sys.stdout.buffer.write((line + '\n').encode('utf-8', 'surrogateescape'))
    sys.stdout.flush()


def print_progress(line):
    """Print line over the one print_progress() printed last, if it's the last line printed, for
    progress that changes often (e.g. a count). Only on a terminal: elsewhere it would be a line per
    change."""
    global _is_progress_shown
    if not sys.stdout.isatty():
        return
    # Back to the line's start, and clear it, in case the new one is shorter
    sys.stdout.buffer.write(('\r' + line + '\033[K').encode('utf-8', 'surrogateescape'))
    sys.stdout.flush()
    _is_progress_shown = True


def note_stopped():
    """Say that an action was stopped with Ctrl-C (also on the progress screen's top line), e.g. by an
    action that catches it to say how far it got."""
    global _is_stopped
    _is_stopped = True
    print_line("Stopped (Ctrl-C)", "red")


def show(title, lines, label=None, color=None):
    """Show lines (in color, if given) on a screen under title, until Enter is pressed"""
    with progress_screen(title, label, is_stoppable=False):
        for line in lines:
            print_line(line, color)


# A label's look on a terminal, by its color name: bold, black or white on the color
_LABEL_STYLES = {'green': '\033[1;30;42m', 'red': '\033[1;37;41m'}


@contextlib.contextmanager
def progress_screen(title, label=None, is_stoppable=True, wait=True):
    """Show what's printed inside (an action's progress) on the whole screen, under title, which
    stays on the top line while the lines scroll under it. When the action ends, wait for Enter, so
    its report can be read before the next picker covers it.

    Ctrl-C inside stops the action (which may catch it itself, to say how far it got). label, a
    (text, color) pair (e.g. dryrun.label()), starts the top line. Without wait, it doesn't wait for
    Enter (unless it was stopped), e.g. for an action whose results are shown next anyway. Without is_stoppable, the top line
    doesn't offer Ctrl-C (for messages). Without a terminal, the title and the lines are just printed.
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
    _write("\033[2J\033[H" + _top_line(("Ctrl-C to stop: " if is_stoppable else "") + title, label) +
           "\033[2;%dr\033[2;1H" % (height,))
    try:
        yield
    except KeyboardInterrupt:
        note_stopped()
    finally:
        done = ("Stopped. " if _is_stopped else "Done. ") if is_stoppable else ""
        if wait or _is_stopped:
            # Save the cursor, rewrite the top line, and restore it. What to do first, in case the
            # line is cut.
            _write("\0337\033[1;1H" + _top_line("%sPress Enter to continue: %s" % (done, title), label) +
                   "\0338")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        # Back to scrolling the whole screen, and the cursor below what was shown (where the next
        # line goes, if what's next isn't a picker)
        _write("\033[r\033[%d;1H\n" % (height,))


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

