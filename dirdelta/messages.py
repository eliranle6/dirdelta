"""dirdelta's messages: plain lines, printed between pickers (each picker has the terminal while it's
open), and screens, which show lines until Enter is pressed: progress_screen() for an action's
progress, show() for messages to read before the next picker covers them.
"""
import contextlib
import readline
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


def ask(title, lines, prompt, default='', label=None):
    """Ask for a line of text on a screen under title, below lines, starting as default (to edit).
    Returns it (stripped), or None if the user gave none (empty, or Ctrl-C or Ctrl-D)."""
    readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        with progress_screen(title, label, is_stoppable=False, wait=False,
                             keys=[('Enter', 'done'), ('Ctrl-C', 'back')]):
            for line in lines:
                print_line(line)
            try:
                answer = input(prompt)
            except (EOFError, KeyboardInterrupt):
                answer = ''
    finally:
        readline.set_startup_hook()
    return answer.strip() or None


# A label's look on a terminal, by its color name: bold, black or white on the color
_LABEL_STYLES = {'green': '\033[1;30;42m', 'red': '\033[1;37;41m'}
# The status bar's look (as treepicker's): black on white
_STATUS_STYLE = '\033[30;47m'
_RESET = '\033[0m'


@contextlib.contextmanager
def progress_screen(title, label=None, is_stoppable=True, wait=True, keys=None):
    """Show what's printed inside (an action's progress) on the whole screen, laid out as the
    pickers are: title on the top line, the lines scrolling under it, and at the bottom, a status
    bar (label, a (text, color) pair such as dryrun.label(), and whether the action is working, done
    or stopped) and a row of the keys (Ctrl-C to stop it while it works; Enter to continue once
    it's done). When the action ends, wait for Enter, so its report can be read before the next
    picker covers it.

    Ctrl-C inside stops the action (which may catch it itself, to say how far it got). Without
    wait, it doesn't wait for Enter (unless it was stopped), e.g. for an action whose results are
    shown next anyway. Without is_stoppable, it's not an action (e.g. messages): no Ctrl-C, and no
    status. keys: the keys row while it's shown ([(key, what it does)]), if not those. Without a
    terminal, the title and the lines are just printed.
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
    if keys is None:
        keys = [('Ctrl-C', 'stop')] if is_stoppable else []
    # Clear the screen, the title on the top line, the bars at the bottom, and the lines scrolling
    # between them (a scroll region)
    _write("\033[2J\033[H\033[1m" + _fit(title) + _RESET + "\033[2;%dr" % (max(2, height - 2),) +
           _bottom(height, label, "Working..." if is_stoppable else "", keys) + "\033[2;1H")
    try:
        yield
    except KeyboardInterrupt:
        note_stopped()
    finally:
        if wait or _is_stopped:
            status = ("Stopped (Ctrl-C)" if _is_stopped else "Done") if is_stoppable else ""
            # Saving the cursor, and back to it after
            _write("\0337" + _bottom(height, label, status, [('Enter', 'continue')]) + "\0338")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        # Back to scrolling the whole screen, and the cursor at its bottom (where the next line
        # goes, if what's next isn't a picker)
        _write("\033[r\033[%d;1H\033[2K\033[%d;1H\033[2K" % (height - 1, height))


def _bottom(height, label, status, keys):
    """The bottom two rows: the status bar (label, then status, over the whole width), then the keys
    row, each key in reverse video then what it does (as treepicker's)"""
    width = shutil.get_terminal_size().columns - 1
    bar = ""
    if label is not None:
        label_text = " %s " % (label[0],)
        bar = _LABEL_STYLES.get(label[1], "\033[1m") + label_text + _RESET + _STATUS_STYLE + " "
        width -= len(label_text) + 1
    else:
        bar = _STATUS_STYLE
    bar += _fit((" " + status) if status else "", width).ljust(max(0, width)) + _RESET
    keys_row = ""
    for key, text in keys:
        keys_row += "\033[7m %s %s %s  " % (key, _RESET, text)
    return "\033[%d;1H\033[2K%s\033[%d;1H\033[2K%s" % (height - 1, bar, height, keys_row)


def _fit(text, width=None):
    """text cut to the screen's width (or width)"""
    width = shutil.get_terminal_size().columns - 1 if width is None else width
    return text[:max(0, width)]


def _write(text):
    sys.stdout.write(text)
    sys.stdout.flush()
