"""dirdelta's pickers: they run the treepicker program, from github.com/eliranle6/treepicker.

Like fzf, treepicker draws on the terminal itself and prints what was picked, so each pick runs it as
a subprocess (see docs/treepicker-integration.md), found by programs.find() ($DIRDELTA_PICKER, or
else where make install, make deploy or make build put it, or else on PATH).
"""
import collections
import os
import subprocess
import tempfile
import threading

from dirdelta import entries
from dirdelta import dryrun
from dirdelta import programs

PROGRAM_ENV_VAR = 'DIRDELTA_PICKER'
PROGRAM_NAME = 'treepicker'

# treepicker's exit code when the user quit without picking
_EXIT_CODE_QUIT = 1

# How often a menu's options are asked again what they're shown as (see pick_option())
SHOWN_AS_INTERVAL = 0.25


class PickerError(programs.ProgramError):
    pass


# What shown_as (see pick_option()) shows an option as when it can't be picked: in grey, with Enter
# doing nothing on it
Disabled = collections.namedtuple('Disabled', ['text'])

# What pick_files() returns: the key that ended picking ('' for Enter), the selected node's relpath
# ('' for the root), to show it again there, and the files picked
Picked = collections.namedtuple('Picked', ['key', 'selected', 'files'])


def pick_from_tree(tree, header='', dirs_only=False, root_name=None):
    """Let the user pick a node of a DirTree (with dirs_only, only of its dirs), its root shown as
    root_name (default: the tree's displayname()). Returns [the picked node's data (entry)], or None
    if the user quit."""
    args = ['--typed', '--root', root_name or tree.displayname()] + _header_args(header)
    if dirs_only:
        args.append('--dirs-only')
    picked_paths = _run(args + ['-'], list(_tree_paths(tree)))
    if picked_paths is None:
        return None
    # The root is printed as '.'; its id is ''
    return [tree.get_node('' if path == '.' else path).data for path in picked_paths]


def pick_files(rootpath, relpaths, header='', picked=None, label=None, keys='', selected=None,
               previews=None):
    """Let the user pick some of the files at relpaths (relative to rootpath, each dir's files and
    subdirs together, in the order to show them, as dirdiff lists them). Picking a dir picks the
    files under it. Returns a Picked: the picked ones (of relpaths), in that order, and where the
    selection was; or None if the user quit. picked (relpaths, e.g. what an earlier call returned)
    start picked. label, if given, is (text, color): a label shown after the mode's. keys (e.g.
    'r'): keys that end picking too, for the caller to act on the selected file or dir (the
    Picked's key), with what's picked so far. selected: the relpath of the file or dir to start
    with selected ('' the root), e.g. the Picked's, to go on where it was.

    previews, if given, is called on a thread of its own as soon as the picker is shown, with a
    send(found=None, default=None) for what to show beside the tree, in a column on the right:
    found is {relpath: lines} for files or dirs ('' the root), shown while one is selected, and
    default, if not None, the lines of the ones without any (e.g. how far previews has got). It
    may send as it goes, for the picker shows each at once. send raises PickerClosed once the
    picker is gone (and previews should then stop, letting it go up): pick_files() returns only
    once previews has returned.

    Only the files are sent: treepicker adds their dirs, so no tree is built here."""
    args = ['--typed', '--root', rootpath, '-m', '--print-selection'] + _header_args(header)
    if keys:
        args += ['--expect', keys]
    if selected is not None:
        args += ['--select', selected or '.']
    with tempfile.NamedTemporaryFile('wb', prefix='dirdelta-picked-') as picked_file:
        if picked:
            picked_file.write(_null_terminated(picked))
            picked_file.flush()
            args += ['--picked', picked_file.name]
        picked_paths = _run(args + ['-'], ('f ' + relpath for relpath in relpaths),
                            label=label, previews=previews)
    if picked_paths is None:
        return None
    key = ''
    if keys:
        # The key that ended it first (none for Enter)
        key, picked_paths = picked_paths[0], picked_paths[1:]
    # Then the selected node
    selected, picked_paths = picked_paths[0], picked_paths[1:]
    # What's picked includes the dirs whose files all are
    files = set(relpaths)
    return Picked(key, '' if selected == '.' else selected,
                  [path for path in picked_paths if path in files])


def pick_under_dir(dirpath, max_depth=None, dirs_only=False, lazy=False, header=''):
    """Let the user pick a file or dir (with dirs_only, a dir) under the local dir dirpath, scanned
    by treepicker itself: all of it at the start, or with lazy, a dir at a time, as it's shown
    (for a huge one, like /). Returns the picked one's full path, or None if the user quit."""
    args = [] if max_depth is None else ['--max-depth', str(max_depth)]
    if dirs_only:
        args.append('--dirs-only')
    if lazy:
        args.append('--lazy')
    picked = _run(args + _header_args(header) + [dirpath], None)
    if picked is None:
        return None
    return dirpath if picked[0] == '.' else os.path.join(dirpath, picked[0])


def pick_option(options, header='', shown_as=None, label=None):
    """Let the user pick one of the options (strings). Returns it, or None if the user quit.

    shown_as, if given, is called again and again while the menu is shown (every
    SHOWN_AS_INTERVAL seconds, on another thread), and returns {option: what to show it as} for
    the options to show otherwise than as themselves, e.g. with a count that's coming in: a
    string, or a Disabled for one that can't be picked (until shown_as says otherwise). What's
    returned is still the option itself. label: as pick_files()'s."""
    args = ['--list', '--root', 'Options'] + _header_args(header)
    picked = _run(args, options, shown_as, label)
    return None if picked is None else picked[0]


def _tree_paths(tree):
    """The tree's nodes' paths for treepicker (relative, '/'-separated), each dir before what's in
    it, siblings sorted by name, each after its type for --typed ('f ' a file, 'd ' a dir). The root
    isn't one: it's treepicker's root."""
    stack = list(reversed(_sorted_children(tree, tree.root)))
    while stack:
        node = stack.pop()
        kind = 'f' if isinstance(node.data, entries.FileEntry) else 'd'
        yield '%s %s' % (kind, node.identifier)
        stack.extend(reversed(_sorted_children(tree, node.identifier)))


def _sorted_children(tree, identifier):
    return sorted(tree.children(identifier), key=lambda node: node.tag)


def _header_args(header):
    return ['--header', header] if header else []


def _run(args, input_items, shown_as=None, label=None, previews=None):
    """Run treepicker with args and the items (or None) on its stdin, and with shown_as (see
    pick_option()) sending it what to show the items as, and previews (see pick_files()) what to
    show beside them. Returns what was picked, or None if the user quit. Every picker shows whether
    it's a dry run, and then label (text, color), if given."""
    command = [_find_program(), '-0']
    for text, color in [dryrun.label()] + ([label] if label else []):
        command += ['--label', text, '--label-color', color]
    command += args
    # Each sender writes to a pipe of its own, on a thread of its own, while treepicker runs
    senders = []
    if shown_as is not None:
        senders.append(('--updates', lambda fd, is_done: _send_updates(fd, shown_as, is_done)))
    if previews is not None:
        senders.append(('--preview', lambda fd, is_done: _send_previews(fd, previews, is_done)))
    read_fds, write_fds = [], []
    for option, _ in senders:
        read_fd, write_fd = os.pipe()
        read_fds.append(read_fd)
        write_fds.append(write_fd)
        command += [option, str(read_fd)]
    is_done = threading.Event()
    threads = []
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
                    pass_fds=read_fds)
            except OSError as error:
                raise PickerError('Cannot run %s: %s' % (command[0], error))
            finally:
                # treepicker has its own copies
                for read_fd in read_fds:
                    os.close(read_fd)
        for (_, send), write_fd in zip(senders, write_fds):
            threads.append(threading.Thread(target=send, args=(write_fd, is_done), daemon=True))
        write_fds = []  # The senders close them
        for thread in threads:
            thread.start()
        stdout, _ = process.communicate()
    finally:
        is_done.set()
        for write_fd in write_fds:
            os.close(write_fd)
        # So nothing a sender started (e.g. a find) outlives the picker
        for thread in threads:
            thread.join()
    if process.returncode == _EXIT_CODE_QUIT:
        return None
    if process.returncode != 0:
        raise PickerError('%s failed (exit code %d)' % (command[0], process.returncode))
    output = stdout.decode('utf-8', 'surrogateescape')
    # Each ends with '\0'; with --expect the first may be empty
    return output.split('\0')[:-1]


def _send_updates(fd, shown_as, is_done):
    """Send treepicker what shown_as() says to show the items as, as it changes, until is_done (or
    treepicker is gone)"""
    sent = {}
    with open(fd, 'wb') as updates:
        while True:
            changed = {item: shown for item, shown in shown_as().items() if sent.get(item) != shown}
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
    """treepicker's --updates line showing item as shown (a string, or Disabled)"""
    if isinstance(shown, Disabled):
        return '%s\t%s\tdisabled' % (item, shown.text)
    return '%s\t%s' % (item, shown)


class PickerClosed(Exception):
    """Raised by pick_files()'s previews' send() once the picker is gone"""


def _send_previews(fd, previews, is_done):
    """Call previews(send), with send() writing what it's given to treepicker (see pick_files()),
    until previews returns, or treepicker is gone (is_done, or the pipe is broken). Closes fd."""
    def send(found=None, default=None):
        if is_done.is_set():
            raise PickerClosed()
        items = [_preview(relpath or '.', lines) for relpath, lines in (found or {}).items()]
        if default is not None:
            # An empty path: the lines of the ones without any
            items.append(_preview('', default))
        data = _null_terminated(items)
        try:
            while data:
                data = data[os.write(fd, data):]
        except BrokenPipeError:
            raise PickerClosed()
    try:
        previews(send)
    except PickerClosed:
        pass
    finally:
        os.close(fd)


def _preview(path, lines):
    """treepicker's --preview line showing lines for path"""
    return path + '\t' + '\t'.join(_one_line(line) for line in lines)


def _one_line(text):
    """text without what would end a --preview line, or the preview's line itself (e.g. a file
    name's tab), shown as '?' like treepicker shows control characters"""
    return text.replace('\t', '?').replace('\n', '?').replace('\0', '?')


def _null_terminated(items):
    # surrogateescape: file names needn't be valid UTF-8, and come back as they went
    return b''.join(item.encode('utf-8', 'surrogateescape') + b'\0' for item in items)


def _find_program():
    return programs.find(PROGRAM_NAME, PROGRAM_ENV_VAR)
