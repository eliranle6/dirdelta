"""Running treepicker: its arguments, its input and output, and the threads beside it (see
command.py)"""
import functools

from dirdelta.ui.picker.command import PickerError, _Command
from dirdelta.ui.picker.updates import _send_updates, _with_ambient_status

# treepicker's exit code when the user quit without picking
_EXIT_CODE_QUIT = 1


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
    command = _Command(args, label)
    if side is not None:
        command.add_side(side)
    shown_as = _with_ambient_status(shown_as)
    if shown_as is not None:
        command.jobs.append(functools.partial(_send_updates, command.pipe('--updates', True), shown_as,
                                              command.is_done))
    command.add_readers(command.add_previews(previews, on_selection, images, notify))
    process, stdout = command.run(input_items)
    if process.returncode == _EXIT_CODE_QUIT:
        return None
    if process.returncode != 0:
        raise PickerError('%s failed (exit code %d)' % (command.args[0], process.returncode))
    output = stdout.decode('utf-8', 'surrogateescape')
    # Each ends with '\0'; with --expect the first may be empty
    return output.split('\0')[:-1]
