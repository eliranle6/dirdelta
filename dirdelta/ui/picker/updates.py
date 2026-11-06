"""What's sent to a running picker as it changes: how its items are shown, the status of what
goes on behind it, and the errors of its threads (logged, as treepicker has the screen)"""
import os
import time
import traceback

from dirdelta.ui.picker.kinds import Colored, Disabled, Skipped
from dirdelta.ui.picker.styles import segments


# Where what goes wrong in a picker's threads is written (rather than on the screen, which
# treepicker has)
ERRORS_LOG = os.path.expanduser('~/.cache/dirdelta/errors.log')

# How often a menu's options are asked again what they're shown as (see pick_option())
SHOWN_AS_INTERVAL = 0.25


# What gives the status of what goes on behind the pickers (set_ambient_status())
_ambient_status = None


def set_ambient_status(parts):
    """parts() is [(text, color)] of what goes on behind the pickers, each on the status bar of every
    picker that says nothing else there, as it changes (see segments())"""
    global _ambient_status
    _ambient_status = parts


def _with_ambient_status(shown_as):
    """shown_as (or None), with the ambient status as its '', unless it has one. Only if there's such
    a status now, or shown_as is sent anyway: a picker with neither needs no updates."""
    if _ambient_status is None or (shown_as is None and not _ambient_status()):
        return shown_as
    was_shown = []

    def shown():
        now = dict(shown_as()) if shown_as is not None else {}
        if '' not in now:
            parts = _ambient_status()
            if parts or was_shown:
                now[''] = segments(parts)
                was_shown.append(True)
        return now
    return shown


def _logging_errors(job):
    """Run job (a picker's thread's), writing what it raises to ERRORS_LOG, not on the screen"""
    try:
        job()
    except Exception:
        _log_error()


def _log_error():
    """Write the exception being handled, with its traceback, to ERRORS_LOG"""
    try:
        os.makedirs(os.path.dirname(ERRORS_LOG), exist_ok=True)
        with open(ERRORS_LOG, 'a') as log:
            log.write("%s\n%s\n" % (time.strftime('%Y-%m-%d %H:%M:%S'), traceback.format_exc()))
    except OSError:
        pass


# For other threads' errors too (e.g. drivemeta.Uploader's)
log_error = _log_error


def _send_updates(fd, shown_as, is_done):
    """Send treepicker what shown_as() says to show the items as, as it changes, until is_done (or
    treepicker is gone)"""
    sent = {}
    is_logged = False
    with open(fd, 'wb', closefd=False) as updates:
        while True:
            try:
                now = shown_as()
            except Exception:
                # Said on the bottom line, once written down (a bug: the rest stays as it was)
                if not is_logged:
                    _log_error()
                    is_logged = True
                now = {'': segments([("Something went wrong: see %s" % (ERRORS_LOG,), 'red')])}
            changed = {item: shown for item, shown in now.items() if sent.get(item) != shown}
            if changed:
                try:
                    updates.write(_null_terminated(_update(item, shown)
                                                   for item, shown in changed.items()))
                    updates.flush()
                except BrokenPipeError:
                    return
                sent.update(changed)
            if is_done.wait(SHOWN_AS_INTERVAL):
                return


def _update(item, shown):
    """treepicker's --updates line showing item as shown (a string, a Disabled, a Skipped or a
    Colored)"""
    if isinstance(shown, Skipped):
        return '%s\t%s\tskipped' % (item, shown.text)
    if isinstance(shown, Disabled):
        return '%s\t%s\tdisabled' % (item, shown.text)
    if isinstance(shown, Colored):
        return '%s\t%s\tcolor=%s' % (item, shown.text, shown.color)
    return '%s\t%s' % (item, shown)


def _null_terminated(items):
    # surrogateescape: file names needn't be valid UTF-8, and come back as they went
    return b''.join(item.encode('utf-8', 'surrogateescape') + b'\0' for item in items)
