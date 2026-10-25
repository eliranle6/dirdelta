"""dirdelta's pickers: they run the dirpicker program, from github.com/levioctl/cpptree.

Like fzf, dirpicker draws on the terminal itself and prints what was picked, so each pick runs it as
a subprocess (see docs/dirpicker-integration.md), found by programs.find() ($DIRDELTA_PICKER, or
else where make install, make deploy or make build put it, or else on PATH).
"""
import os
import subprocess
import tempfile

from dirdelta import entries
from dirdelta import dryrun
from dirdelta import programs

PROGRAM_ENV_VAR = 'DIRDELTA_PICKER'
PROGRAM_NAME = 'dirpicker'

# dirpicker's exit code when the user quit without picking
_EXIT_CODE_QUIT = 1


class PickerError(programs.ProgramError):
    pass


def pick_from_tree(tree, header=''):
    """Let the user pick a node of a DirTree. Returns [the picked node's data (entry)], or None if
    the user quit."""
    args = ['--typed', '--root', tree.fullpath()] + _header_args(header)
    picked_paths = _run(args + ['-'], list(_tree_paths(tree)))
    if picked_paths is None:
        return None
    # The root is printed as '.'; its id is ''
    return [tree.get_node('' if path == '.' else path).data for path in picked_paths]


def pick_files(rootpath, relpaths, header='', picked=None):
    """Let the user pick some of the files at relpaths (relative to rootpath, each dir's files and
    subdirs together, in the order to show them, as dirdiff lists them). Picking a dir picks the
    files under it. Returns the picked ones (of relpaths), in that order, or None if the user quit.
    picked (relpaths, e.g. what an earlier call returned) start picked.

    Only the files are sent: dirpicker adds their dirs, so no tree is built here."""
    args = ['--typed', '--root', rootpath, '-m'] + _header_args(header)
    with tempfile.NamedTemporaryFile('wb', prefix='dirdelta-picked-') as picked_file:
        if picked:
            picked_file.write(_null_terminated(picked))
            picked_file.flush()
            args += ['--picked', picked_file.name]
        picked_paths = _run(args + ['-'], ('f ' + relpath for relpath in relpaths))
    if picked_paths is None:
        return None
    # What's picked includes the dirs whose files all are
    files = set(relpaths)
    return [path for path in picked_paths if path in files]


def pick_under_dir(dirpath, max_depth=None):
    """Let the user pick a file or dir under the local dir dirpath, scanned by dirpicker itself.
    Returns the picked one's full path, or None if the user quit."""
    args = [] if max_depth is None else ['--max-depth', str(max_depth)]
    picked = _run(args + _header_args('') + [dirpath], None)
    if picked is None:
        return None
    return dirpath if picked[0] == '.' else os.path.join(dirpath, picked[0])


def pick_option(options, header=''):
    """Let the user pick one of the options (strings). Returns it, or None if the user quit."""
    picked = _run(['--list', '--root', 'Options'] + _header_args(header), options)
    return None if picked is None else picked[0]


def _tree_paths(tree):
    """The tree's nodes' paths for dirpicker (relative, '/'-separated), each dir before what's in
    it, siblings sorted by name, each after its type for --typed ('f ' a file, 'd ' a dir). The root
    isn't one: it's dirpicker's root."""
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


def _run(args, input_items):
    """Run dirpicker with args and the items (or None) on its stdin. Returns what was picked, or
    None if the user quit. Every picker shows whether it's a dry run."""
    label, label_color = dryrun.label()
    command = [_find_program(), '-0', '--label', label, '--label-color', label_color] + args
    input_bytes = None if input_items is None else _null_terminated(input_items)
    try:
        result = subprocess.run(command, input=input_bytes, stdout=subprocess.PIPE,
                                stdin=None if input_bytes is not None else subprocess.DEVNULL)
    except OSError as error:
        raise PickerError('Cannot run %s: %s' % (command[0], error))
    if result.returncode == _EXIT_CODE_QUIT:
        return None
    if result.returncode != 0:
        raise PickerError('%s failed (exit code %d)' % (command[0], result.returncode))
    output = result.stdout.decode('utf-8', 'surrogateescape')
    return [item for item in output.split('\0') if item]


def _null_terminated(items):
    # surrogateescape: file names needn't be valid UTF-8, and come back as they went
    return b''.join(item.encode('utf-8', 'surrogateescape') + b'\0' for item in items)


def _find_program():
    return programs.find(PROGRAM_NAME, PROGRAM_ENV_VAR)
