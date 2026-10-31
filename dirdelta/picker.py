"""dirdelta's pickers: they run the treepicker program, from github.com/eliranle6/treepicker.

Like fzf, treepicker draws on the terminal itself and prints what was picked, so each pick runs it as
a subprocess (see docs/treepicker-integration.md), found by programs.find() (where make install,
make deploy or make build put it, or else on PATH).
"""
import collections
import contextlib
import functools
import os
import subprocess
import tempfile
import threading
import time
import traceback

from dirdelta import entries
from dirdelta import dryrun
from dirdelta import programs

PROGRAM_NAME = 'treepicker'

# treepicker's exit code when the user quit without picking
_EXIT_CODE_QUIT = 1

# Where what goes wrong in a picker's threads is written (rather than on the screen, which
# treepicker has)
ERRORS_LOG = os.path.expanduser('~/.cache/dirdelta/errors.log')

# How often a menu's options are asked again what they're shown as (see pick_option())
SHOWN_AS_INTERVAL = 0.25


class PickerError(programs.ProgramError):
    pass


# What shown_as (see pick_option()) shows an option as when it can't be picked: in grey, with Enter
# doing nothing on it
Disabled = collections.namedtuple('Disabled', ['text'])

# Where the user is, the screens' breadcrumbs: the places entered (see place()), after the program's
# name. A menu's tree's root shows them (treepicker shows the path to the selection after it).
PROGRAM = 'dirdelta'
_trail = []
# What the trail's places are shown apart by, as treepicker shows a path
TRAIL_SEPARATOR = ' > '


@contextlib.contextmanager
def place(name):
    """Inside, the menus' breadcrumbs end with name (e.g. 'Sync eliran \u21c4 cloud/eliran')"""
    _trail.append(name)
    try:
        yield
    finally:
        _trail.pop()


def trail(title=None):
    """The breadcrumbs, as a menu's root shows them: the program, the places, and title, if given"""
    return TRAIL_SEPARATOR.join([PROGRAM] + _trail + ([title] if title else []))


# A preview's line starting with it, a label color's name and it again is shown highlighted (see
# highlighted())
HIGHLIGHT_MARK = '\x01'


def highlighted(text, color='green'):
    """A pick_files() preview's line, shown bold on color (a --label-color), across the column"""
    return '%s%s%s%s' % (HIGHLIGHT_MARK, color, HIGHLIGHT_MARK, text)


def status(parts):
    """A status for shown_as's '' (see pick_files()) of several labels, each in its color: parts is
    [(text, color)] (a --label-color, or 'orange'); the empty ones are left out"""
    return ''.join('%s%s%s%s' % (HIGHLIGHT_MARK, color, HIGHLIGHT_MARK, text) for text, color in parts if text)


# What pick_files() returns: the key that ended picking ('' for Enter), the selected node's relpath
# ('' for the root), to show it again there, and the files picked
Picked = collections.namedtuple('Picked', ['key', 'selected', 'files'])


def pick_from_tree(tree, header='', dirs_only=False, root_name=None, keys='', key_hints=()):
    """Let the user pick a node of a DirTree (with dirs_only, only of its dirs), its root shown as
    root_name (default: the tree's displayname()). Returns [the picked node's data (entry)], or None
    if the user quit. With keys (e.g. 'n'), keys that end picking too: it returns (the key, '' for
    Enter; [the picked or selected node's data]), or None."""
    args = (['--typed', '--root', root_name or tree.displayname()] + _header_args(header) + _keys_args(keys) +
            _help_args(key_hints, ()))
    if dirs_only:
        args.append('--dirs-only')
    picked_paths = _run(args + ['-'], list(_tree_paths(tree)))
    if picked_paths is None:
        return None
    key, picked_paths = _key_and_selected(keys, picked_paths)
    # The root is printed as '.'; its id is ''
    picked = [tree.get_node('' if path == '.' else path).data for path in picked_paths]
    return (key, picked) if keys else picked


def pick_files(rootpath, relpaths, header='', picked=None, label=None, keys='', selected=None,
               previews=None, on_selection=None, shown_as=None, notify_keys='', on_notify=None,
               enter_picks_selection=False, key_hints=(), help_lines=()):
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

    key_hints: [(key, what it does here)] for the keys row at the bottom (the caller's keys, or
    treepicker's, e.g. ('Enter', 'choose what to do')); help_lines: lines for its ? help (e.g. what
    the tags mean).

    Only the files are sent: treepicker adds their dirs, so no tree is built here."""
    args = (['--typed', '--root', rootpath, '-m', '--print-selection'] + _header_args(header) +
            _help_args(key_hints, help_lines))
    if enter_picks_selection:
        args.append('--enter-picks-selection')
    if keys:
        args += ['--expect', keys]
    if selected is not None:
        args += ['--select', selected or '.']
    with tempfile.NamedTemporaryFile('wb', prefix='dirdelta-picked-') as picked_file:
        if picked:
            picked_file.write(_null_terminated(picked))
            picked_file.flush()
            args += ['--picked', picked_file.name]
        notify = None
        if notify_keys and on_notify is not None:
            files = set(relpaths)
            notify = (notify_keys, lambda key, selected, picked: on_notify(
                key, selected, [path for path in picked if path in files]))
        picked_paths = _run(args + ['-'], ('f ' + relpath for relpath in relpaths),
                            shown_as=shown_as, label=label, previews=previews,
                            on_selection=on_selection, notify=notify)
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


def view_files(rootpath, relpaths, header='', previews=None, label=None, shown_as=None, on_selection=None,
               key_hints=(), help_lines=()):
    """Show the files at relpaths (relative to rootpath, as pick_files() takes them), e.g. what an
    action will make, with previews ({relpath: lines}) beside them, to look through. Returns
    whether the user pressed Enter (rather than quit). shown_as, on_selection: as pick_files()'s."""
    args = ['--typed', '--root', rootpath] + _header_args(header) + _help_args(key_hints, help_lines)
    send_previews = None
    if previews:
        send_previews = lambda send: send(previews, default=[])
    return _run(args + ['-'], ('f ' + relpath for relpath in relpaths), shown_as=shown_as, label=label,
                previews=send_previews, on_selection=on_selection) is not None


def pick_under_dir(dirpath, max_depth=None, dirs_only=False, lazy=False, header='', keys='', key_hints=()):
    """Let the user pick a file or dir (with dirs_only, a dir) under the local dir dirpath, scanned
    by treepicker itself: all of it at the start, or with lazy, a dir at a time, as it's shown
    (for a huge one, like /). Returns the picked one's full path, or None if the user quit. With
    keys (e.g. 'n'), keys that end picking too: it returns (the key, '' for Enter; the picked or
    selected one's full path), or None."""
    args = [] if max_depth is None else ['--max-depth', str(max_depth)]
    if dirs_only:
        args.append('--dirs-only')
    if lazy:
        args.append('--lazy')
    picked = _run(args + _header_args(header) + _keys_args(keys) + _help_args(key_hints, ()) + [dirpath], None)
    if picked is None:
        return None
    key, picked = _key_and_selected(keys, picked)
    path = dirpath if picked[0] == '.' else os.path.join(dirpath, picked[0])
    return (key, path) if keys else path


def _keys_args(keys):
    """A one-node picker's args for keys that end picking too: they're printed first, then the
    selected node (for Enter, the picked one)"""
    return ['--expect', keys, '--print-selection'] if keys else []


def _key_and_selected(keys, printed):
    """With keys (see _keys_args()), the key ('' for Enter) and [the selected node's path]; else
    no key, and printed as it is"""
    if not keys:
        return '', printed
    return printed[0], printed[1:2]


def pick_option(options, header='', shown_as=None, label=None, selected=None, title=None, key_hints=(),
                help_lines=()):
    """Let the user pick one of the options (strings). Returns it, or None if the user quit.

    shown_as, if given, is called again and again while the menu is shown (every
    SHOWN_AS_INTERVAL seconds, on another thread), and returns {option: what to show it as} for
    the options to show otherwise than as themselves, e.g. with a count that's coming in: a
    string, or a Disabled for one that can't be picked (until shown_as says otherwise). What's
    returned is still the option itself. label: as pick_files()'s. selected: the option to start
    with selected (else the first). title: what the menu is, after the breadcrumbs (see place()).
    key_hints, help_lines: as pick_files()'s."""
    args = ['--list', '--root', trail(title)] + _header_args(header) + _help_args(key_hints, help_lines)
    if selected is not None:
        args += ['--select', selected]
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


def _help_args(key_hints, help_lines):
    """treepicker's args for the keys row's keys ([(key, what it does here)], e.g. ('#', 'hashing'))
    and the lines its ? help adds"""
    args = []
    for key, text in key_hints:
        args += ['--key', key, text]
    for line in help_lines:
        args += ['--help-line', line]
    return args


def _run(args, input_items, shown_as=None, label=None, previews=None, on_selection=None, notify=None):
    """Run treepicker with args and the items (or None) on its stdin, and with shown_as (see
    pick_option()) sending it what to show the items as, and previews and on_selection (see
    pick_files()) what to show beside them, and notify (keys, a function of what they say) what
    to do on its keys. Returns what was picked, or None if the user quit.
    Every picker shows whether it's a dry run, and then label (text, color), if given."""
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
    if shown_as is not None:
        jobs.append(functools.partial(_send_updates, pipe('--updates', True), shown_as, is_done))
    if previews is not None or on_selection is not None:
        preview_sender = _PreviewSender(pipe('--preview', True), is_done)
        if previews is not None:
            jobs.append(functools.partial(preview_sender.run, previews))
        if on_selection is not None:
            selection = Selection()
            jobs.append(functools.partial(_read_selection, pipe('--selection', False), selection))
            jobs.append(functools.partial(preview_sender.run,
                                          lambda send: on_selection(selection, send)))
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
    if process.returncode == _EXIT_CODE_QUIT:
        return None
    if process.returncode != 0:
        raise PickerError('%s failed (exit code %d)' % (command[0], process.returncode))
    output = stdout.decode('utf-8', 'surrogateescape')
    # Each ends with '\0'; with --expect the first may be empty
    return output.split('\0')[:-1]


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
                now = {'': status([("Something went wrong: see %s" % (ERRORS_LOG,), 'red')])}
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
    """treepicker's --updates line showing item as shown (a string, or Disabled)"""
    if isinstance(shown, Disabled):
        return '%s\t%s\tdisabled' % (item, shown.text)
    return '%s\t%s' % (item, shown)


class PickerClosed(Exception):
    """Raised by pick_files()'s previews' send(), and its on_selection's Selection, once the picker
    is gone"""


class Selection(object):
    """Where a pick_files() picker's selection is (a relpath, '' for the root), as treepicker says
    while it's shown, for its on_selection"""

    def __init__(self):
        self._condition = threading.Condition()
        self._relpath = None
        # How many times it moved, and how many of them wait_next() has returned
        self._nr_moves = self._nr_seen = 0
        self._is_closed = False

    def wait_next(self, timeout=None):
        """The selection, once it has moved since wait_next() last returned it (or at first), or
        None if timeout (seconds) passes first. Raises PickerClosed once the picker is gone."""
        with self._condition:
            self._condition.wait_for(lambda: self._is_closed or self._nr_moves != self._nr_seen,
                                     timeout)
            if self._is_closed:
                raise PickerClosed()
            if self._nr_moves == self._nr_seen:
                return None
            self._nr_seen = self._nr_moves
            return self._relpath

    def is_at(self, relpath):
        """Whether the selection is at relpath now. Raises PickerClosed once the picker is gone."""
        with self._condition:
            if self._is_closed:
                raise PickerClosed()
            return self._relpath == relpath

    def _move(self, relpath):
        with self._condition:
            self._relpath = relpath
            self._nr_moves += 1
            self._condition.notify_all()

    def _close(self):
        with self._condition:
            self._is_closed = True
            self._condition.notify_all()


def _read_selection(fd, selection):
    """Move selection as treepicker says the selection moves (each path ending with '\0'), until it
    stops saying (it's gone)"""
    pending = b''
    try:
        for chunk in iter(lambda: os.read(fd, 4096), b''):
            paths = (pending + chunk).split(b'\0')
            pending = paths.pop()
            for path in paths:
                path = path.decode('utf-8', 'surrogateescape')
                selection._move('' if path == '.' else path)
    except OSError:
        pass
    finally:
        selection._close()


def _read_notifications(fd, on_notify):
    """Call on_notify(key, selected relpath, picked relpaths) for each of treepicker's --notify
    records (the key, the selected node's path, the picked ones', each ending with '\\0', and an
    empty item to end it), until it's gone"""
    items, pending = [], b''
    try:
        for chunk in iter(lambda: os.read(fd, 4096), b''):
            parts = (pending + chunk).split(b'\0')
            pending = parts.pop()
            for part in parts:
                if part:
                    items.append(part.decode('utf-8', 'surrogateescape'))
                    continue
                if len(items) >= 2:
                    key, selected, picked = items[0], items[1], items[2:]
                    on_notify(key, '' if selected == '.' else selected, picked)
                items = []
    except OSError:
        pass


class _PreviewSender(object):
    """Writes what's sent to treepicker's --preview pipe (see pick_files()), from any thread"""

    def __init__(self, fd, is_done):
        self._fd = fd
        self._is_done = is_done
        self._lock = threading.Lock()

    def send(self, found=None, default=None):
        if self._is_done.is_set():
            raise PickerClosed()
        items = [_preview(relpath or '.', lines) for relpath, lines in (found or {}).items()]
        if default is not None:
            # An empty path: the lines of the ones without any
            items.append(_preview('', default))
        data = _null_terminated(items)
        # A preview's lines in one piece, whichever thread sends it
        with self._lock:
            try:
                while data:
                    data = data[os.write(self._fd, data):]
            except BrokenPipeError:
                raise PickerClosed()

    def run(self, previews):
        """Call previews(send), until it returns, or treepicker is gone"""
        try:
            previews(self.send)
        except PickerClosed:
            pass


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
    return programs.find(PROGRAM_NAME)
