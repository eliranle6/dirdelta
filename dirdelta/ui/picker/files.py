"""Picking files (pick_files()), and viewing them (view_files())"""
import tempfile

from dirdelta.ui.picker.kinds import Picked, SIDE_KEY
from dirdelta.ui.picker.pictures import IMAGES_KEY
from dirdelta.ui.picker.running import header_args, help_args, run_treepicker
from dirdelta.ui.picker.updates import null_terminated


def pick_files(rootpath, relpaths, header='', picked=None, label=None, keys='', selected=None,
               previews=None, on_selection=None, shown_as=None, notify_keys='', on_notify=None,
               enter_picks_selection=False, key_hints=(), help_lines=(), twice_keys='', side=None,
               none_picked_key_hints=(), images=None, footer=''):
    """Let the user pick some of the files at relpaths (relative to rootpath, each dir's files and
    subdirs together, in the order to show them, as dirdiff lists them). Picking a dir picks the
    files under it. Returns a Picked: the picked ones (of relpaths), in that order, and where the
    selection was; or None if the user quit. picked (relpaths, e.g. what an earlier call returned)
    start picked. label, if given, is (text, color): a label shown after the mode's. keys (e.g.
    'r'): keys that end picking too, for the caller to act on the selected file or dir (the
    Picked's key), with what's picked so far. selected: the relpath of the file or dir to start
    with selected ('' the root), e.g. the Picked's, to go on where it was. With
    enter_picks_selection, Enter with nothing picked picks the selected file (or a dir's files), as
    if Space picked it first.

    previews, if given, is called on a thread of its own as soon as the picker is shown, with a
    send(found=None, default=None) for what to show beside the tree, in a column on the right:
    found is {relpath: lines} for files or dirs ('' the root), shown while one is selected, and
    default, if not None, the lines of the ones without any (e.g. how far previews has got). It
    may send as it goes, for the picker shows each at once. send raises PickerClosed once the
    picker is gone (and previews should then stop, letting it go up): pick_files() returns only
    once previews has returned.

    shown_as, if given: as pick_option()'s, for files (by relpath) to show otherwise than by their
    names, e.g. with a description after the name; and '' for a status to show on the bottom line
    (e.g. that something's being worked out).

    notify_keys (e.g. '\\t', Ctrl-I): keys that don't end picking, but call on_notify(key, the
    selected node's relpath, the files picked so far), on another thread, e.g. to start working
    something out about them in the background.

    on_selection, if given, is called on another thread of its own as soon as the picker is shown,
    with a Selection (where the selection is, as it moves) and the same send(), e.g. to work out
    more about the selected file than previews does for all of them. It too should stop on
    PickerClosed, which the Selection raises too, once the picker is gone.

    images, if given (with previews or on_selection, which make the column), is called on a thread
    of its own with the selected node's relpath, once the selection stays on it a moment, and the
    most pixels the column can show (max_width, max_height): its picture, as images.encoded() makes
    it, shown below its lines (or beside them, if it's portrait); or None for none. IMAGES_KEY
    switches them off and on, for the next pickers too (settings.py).

    key_hints: [(key, what it does here)] for the keys row at the bottom (the caller's keys, or
    treepicker's, e.g. ('Enter', 'choose what to do')); help_lines: lines for its ? help (e.g. what
    the tags mean); none_picked_key_hints: what the keys row says instead of those while nothing's
    picked. footer: lines below the tree, above the bottom lines, e.g. a warning (each plain, or
    styled: see styled()).

    Only the files are sent: treepicker adds their dirs, so no tree is built here."""
    if images is not None:
        help_lines = list(help_lines) + key_help_lines([(IMAGES_KEY, "show or hide the files' pictures (and from now on)")])
    args = (['--typed', '--root', rootpath, '-m', '--print-selection'] + header_args(header) +
            help_args(key_hints, help_lines))
    if footer:
        args += ['--footer', footer]
    if enter_picks_selection:
        args.append('--enter-picks-selection')
    for key, text in none_picked_key_hints:
        args += ['--key-if-none-picked', key, text]
    if keys:
        args += ['--expect', keys]
    if twice_keys:
        # Ending it when pressed twice in a row, e.g. cc (see pick_from_tree())
        args += ['--expect-twice', twice_keys]
    if selected is not None:
        args += ['--select', selected or '.']
    with tempfile.NamedTemporaryFile('wb', prefix='dirdelta-picked-') as picked_file:
        if picked:
            picked_file.write(null_terminated(picked))
            picked_file.flush()
            args += ['--picked', picked_file.name]
        notify = None
        if notify_keys and on_notify is not None:
            files = set(relpaths)
            notify = (notify_keys, lambda key, selected, picked: on_notify(
                key, selected, [path for path in picked if path in files]))
        picked_paths = run_treepicker(args + ['-'], ('f ' + relpath for relpath in relpaths),
                            shown_as=shown_as, label=label, previews=previews,
                            on_selection=on_selection, notify=notify, side=side, images=images)
    if picked_paths is None:
        return None
    key = ''
    if keys or twice_keys or (side is not None and side.is_enter_picking):
        # The key that ended it first (none for Enter)
        key, picked_paths = _twice(picked_paths[0], twice_keys), picked_paths[1:]
    # Then the selected node, and after Enter in the side tree, its selected one
    selected, picked_paths = picked_paths[0], picked_paths[1:]
    side_selected, side_pressed = None, ''
    if key == SIDE_KEY:
        side_selected, picked_paths = picked_paths[0], picked_paths[1:]
        side_selected = '' if side_selected == '.' else side_selected
        if side.keys:
            side_pressed, picked_paths = picked_paths[0], picked_paths[1:]
    # What's picked includes the dirs whose files all are
    files = set(relpaths)
    return Picked(key, '' if selected == '.' else selected,
                  [path for path in picked_paths if path in files], side_selected, side_pressed)


def view_files(rootpath, relpaths, header='', previews=None, label=None, shown_as=None, on_selection=None,
               key_hints=(), help_lines=()):
    """Show the files at relpaths (relative to rootpath, as pick_files() takes them), e.g. what an
    action will make, with previews ({relpath: lines}) beside them, to look through. Returns
    whether the user pressed Enter (rather than quit). shown_as, on_selection: as pick_files()'s."""
    args = ['--typed', '--root', rootpath] + header_args(header) + help_args(key_hints, help_lines)
    send_previews = None
    if previews:
        send_previews = lambda send: send(previews, default=[])
    return run_treepicker(args + ['-'], ('f ' + relpath for relpath in relpaths), shown_as=shown_as, label=label,
                previews=send_previews, on_selection=on_selection) is not None


def key_help_lines(key_hints):
    """help_lines (see pick_files()) for keys that work but aren't in the keys row, which has little
    room: [(key, what it does here)], as treepicker's ? help lists the row's"""
    return ["  %-17s%s" % hint for hint in key_hints]


def keys_args(keys, twice_keys=''):
    """A one-node picker's args for keys that end picking too (and twice_keys, pressed twice):
    they're printed first, then the selected node (for Enter, the picked one)"""
    if not keys and not twice_keys:
        return []
    return ((['--expect', keys] if keys else []) + (['--expect-twice', twice_keys] if twice_keys else []) +
            ['--print-selection'])


def key_and_selected(keys, printed, twice_keys=''):
    """With keys (see keys_args()), the key ('' for Enter; a twice_keys' doubled) and [the
    selected node's path]; else no key, and printed as it is"""
    if not keys and not twice_keys:
        return '', printed
    return _twice(printed[0], twice_keys), printed[1:2]


def _twice(key, twice_keys):
    """The key treepicker printed, doubled if it's one of twice_keys (pressed twice: 'cc')"""
    return key * 2 if key and key in twice_keys else key
