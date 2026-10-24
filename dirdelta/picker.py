"""dirdelta's pickers: they run the dirpicker program, from github.com/levioctl/cpptree.

Like fzf, dirpicker draws on the terminal itself and prints what was picked, so each pick runs it as
a subprocess (see docs/dirpicker-integration.md). It's found as $DIRDELTA_PICKER; else next to the
Python running dirdelta, where make install and make deploy put it; else as the repo's own build
(lib/cpptree/build/dirpicker, from make build), for running from source; else on PATH.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from dirdelta import entries
from dirdelta import dryrun

PROGRAM_ENV_VAR = 'DIRDELTA_PICKER'
PROGRAM_NAME = 'dirpicker'
# Where make build puts it, when running from the source tree
SOURCE_TREE_PROGRAM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'lib', 'cpptree', 'build', PROGRAM_NAME)

# dirpicker's exit code when the user quit without picking
_EXIT_CODE_QUIT = 1


class PickerError(Exception):
    pass


def pick_from_tree(tree, header='', multi=False, picked=None):
    """Let the user pick from a DirTree. Returns the picked nodes' data (entries), in the tree's
    order, or None if the user quit.

    With multi, they pick several: picking a dir picks everything under it, dirs included. picked
    (entries, e.g. what an earlier call returned) start picked.
    """
    paths = list(_tree_paths(tree))
    args = ['--typed', '--root', tree.fullpath()] + (['-m'] if multi else []) + _header_args(header)
    with tempfile.NamedTemporaryFile('wb', prefix='dirdelta-picked-') as picked_file:
        if picked:
            picked_file.write(_null_terminated(entry.relpath or '.' for entry in picked))
            picked_file.flush()
            args += ['--picked', picked_file.name]
        picked_paths = _run(args + ['-'], paths)
    if picked_paths is None:
        return None
    # The root is printed as '.'; its id is ''
    return [tree.get_node('' if path == '.' else path).data for path in picked_paths]


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
    program = os.environ.get(PROGRAM_ENV_VAR)
    if program:
        return program
    # Not resolving sys.executable's links: a venv's python links to the system's
    for candidate in (os.path.join(os.path.dirname(sys.executable), PROGRAM_NAME), SOURCE_TREE_PROGRAM):
        if os.access(candidate, os.X_OK):
            return candidate
    program = shutil.which(PROGRAM_NAME)
    if not program:
        raise PickerError(
            '%s was not found. Build it with make build (or install it with make install or make '
            'deploy), or point $%s at it.' % (PROGRAM_NAME, PROGRAM_ENV_VAR))
    return program
