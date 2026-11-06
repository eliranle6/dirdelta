"""Running treepicker: its arguments, its input and output, and the threads beside it"""
import functools
import os
import subprocess
import tempfile
import threading

from dirdelta.ui.picker.kinds import SIDE_KEY
from dirdelta.ui.picker.pictures import IMAGES_KEY, _Images
from dirdelta.ui.picker.places import _trail
from dirdelta.ui.picker.previews import _PreviewSender
from dirdelta.ui.picker.selection import Selection, _follow, _read_notifications, _read_selection
from dirdelta.ui.picker.updates import _logging_errors, _null_terminated, _send_updates, _with_ambient_status
from dirdelta.util import dryrun
from dirdelta.util import programs


PROGRAM_NAME = 'treepicker'

# treepicker's exit code when the user quit without picking
_EXIT_CODE_QUIT = 1


class PickerError(programs.ProgramError):
    pass


def _header_args(header):
    return ['--header', header] if header else []


def _help_args(key_hints, help_lines):
    """treepicker's args for the keys row's keys ([(key, what it does here)], e.g. ('#', 'hashing'))
    and the lines its ? help adds"""
    args = []
    for key, text in key_hints:
        args += ['--key', key, text]
    for line in help_lines:
        args += ['--help-line', line]
    return args


def _run(args, input_items, shown_as=None, label=None, previews=None, on_selection=None, notify=None,
         side=None, images=None):
    """Run treepicker with args and the items (or None) on its stdin, and with shown_as (see
    pick_option()) sending it what to show the items as, and previews and on_selection (see
    pick_files()) what to show beside them, and notify (keys, a function of what they say) what
    to do on its keys, and side (a Side) the tree beside it. Returns what was picked, or None if the
    user quit.
    Every picker shows whether it's a dry run, and then label (text, color), if given."""
    shown_as = _with_ambient_status(shown_as)
    command = [_find_program(), '-0']
    for text, color in [dryrun.label()] + ([label] if label else []):
        command += ['--label', text, '--label-color', color]
    if not any(args[i:i + 2] == ['--key', 'q'] for i in range(len(args))):
        # q quits the start menu; anywhere else, it goes back to where the user was
        command += ['--key', 'q', 'back' if _trail else 'quit']
    command += args
    is_done = threading.Event()
    # Pipes to treepicker (which reads --updates and --preview) and from it (it writes
    # --selection), each served by a thread of its own while it runs: treepicker's ends, and ours
    child_fds, our_fds = [], []

    def pipe(option, is_read_by_child):
        read_fd, write_fd = os.pipe()
        child_fd, our_fd = (read_fd, write_fd) if is_read_by_child else (write_fd, read_fd)
        child_fds.append(child_fd)
        our_fds.append(our_fd)
        command.extend([option, str(child_fd)])
        return our_fd

    jobs = []
    # The ones on the selection's moves, each its own (see Selection), all moved by one reader
    selections = []
    side_file = None
    if side is not None:
        side_file = tempfile.NamedTemporaryFile('wb', prefix='dirdelta-side-')
        side_file.write(_null_terminated(side.items))
        side_file.flush()
        command.extend(['--side', side_file.name, '--side-root', side.root_name])
        if side.is_enter_picking:
            command.extend(['--side-key', SIDE_KEY])
        if side.keys:
            command.extend(['--side-expect', side.keys])
        if side.start is not None:
            command.extend(['--side-start', side.start or '.'])
        for key, text in side.key_hints:
            command.extend(['--side-hint', key, text])
        if side.follow is not None:
            selections.append(Selection())
            jobs.append(functools.partial(_follow, selections[-1], side.follow, pipe('--side-select', True)))
    if shown_as is not None:
        jobs.append(functools.partial(_send_updates, pipe('--updates', True), shown_as, is_done))
    if previews is not None or on_selection is not None:
        preview_sender = _PreviewSender(pipe('--preview', True), is_done)
        if previews is not None:
            jobs.append(functools.partial(preview_sender.run, previews))
        if on_selection is not None:
            selection = Selection()
            selections.append(selection)
            jobs.append(functools.partial(preview_sender.run,
                                          lambda send: on_selection(selection, send)))
        if images is not None:
            selections.append(Selection())
            pictures = _Images(selections[-1], images, preview_sender)
            jobs.append(pictures.run)
            # Its key, besides the caller's
            keys, on_notify = notify if notify is not None else ('', None)

            def notified(key, selected, picked, on_notify=on_notify):
                if key == IMAGES_KEY:
                    pictures.toggle(selected)
                elif on_notify is not None:
                    on_notify(key, selected, picked)
            notify = (keys + IMAGES_KEY, notified)
    if selections:
        jobs.append(functools.partial(_read_selection, pipe('--selection', False), selections))
    if notify is not None:
        keys, on_notify = notify
        command.extend(['--notify', keys])
        jobs.append(functools.partial(_read_notifications, pipe('--notify-fd', False), on_notify))
    threads = [threading.Thread(target=_logging_errors, args=(job,), daemon=True) for job in jobs]
    try:
        # From a file, rather than written to a pipe by communicate(): with a sender busy on its
        # thread (holding the GIL), writing a big input would be slow to get the GIL back each time
        with tempfile.TemporaryFile() as input_file:
            if input_items is not None:
                input_file.write(_null_terminated(input_items))
                input_file.seek(0)
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE,
                    stdin=input_file if input_items is not None else subprocess.DEVNULL,
                    pass_fds=child_fds)
            except OSError as error:
                raise PickerError('Cannot run %s: %s' % (command[0], error))
            finally:
                # treepicker has its own copies
                for child_fd in child_fds:
                    os.close(child_fd)
        for thread in threads:
            thread.start()
        stdout, _ = process.communicate()
    finally:
        is_done.set()
        # So nothing a thread started (e.g. a find) outlives the picker. They end once treepicker
        # has: what they send raises PickerClosed, and the selection's pipe ends.
        for thread in threads:
            if thread.is_alive():
                thread.join()
        for our_fd in our_fds:
            os.close(our_fd)
        if side_file is not None:
            side_file.close()
    if process.returncode == _EXIT_CODE_QUIT:
        return None
    if process.returncode != 0:
        raise PickerError('%s failed (exit code %d)' % (command[0], process.returncode))
    output = stdout.decode('utf-8', 'surrogateescape')
    # Each ends with '\0'; with --expect the first may be empty
    return output.split('\0')[:-1]


def _find_program():
    return programs.find(PROGRAM_NAME)
