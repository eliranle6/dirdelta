"""Picking a node of a tree (pick_from_tree()) or a path under a dir (pick_under_dir())"""
import os

from dirdelta.trees import entries
from dirdelta.ui.picker.files import _key_and_selected, _keys_args
from dirdelta.ui.picker.running import _header_args, _help_args, _run


def pick_from_tree(tree, header='', dirs_only=False, root_name=None, keys='', key_hints=(), twice_keys='', excluded=()):
    """Let the user pick a node of a DirTree (with dirs_only, only of its dirs), its root shown as
    root_name (default: the tree's displayname()). Returns [the picked node's data (entry)], or None
    if the user quit. With keys (e.g. 'n'), keys that end picking too: it returns (the key, '' for
    Enter; [the picked or selected node's data]), or None. twice_keys: keys that do so when pressed
    twice in a row (e.g. 'c' for vim's cc), returned doubled ('cc'). excluded: relpaths left out, with
    all in them."""
    args = (['--typed', '--root', root_name or tree.displayname()] + _header_args(header) +
            _keys_args(keys, twice_keys) + _help_args(key_hints, ()))
    if dirs_only:
        args.append('--dirs-only')
    picked_paths = _run(args + ['-'], list(_tree_paths(tree, excluded)))
    if picked_paths is None:
        return None
    key, picked_paths = _key_and_selected(keys, picked_paths, twice_keys)
    # The root is printed as '.'; its id is ''
    picked = [tree.get_node('' if path == '.' else path).data for path in picked_paths]
    return (key, picked) if keys or twice_keys else picked


def pick_under_dir(dirpath, max_depth=None, dirs_only=False, lazy=False, header='', keys='', key_hints=(),
                   twice_keys='', excluded=()):
    """Let the user pick a file or dir (with dirs_only, a dir) under the local dir dirpath, scanned
    by treepicker itself: all of it at the start, or with lazy, a dir at a time, as it's shown
    (for a huge one, like /). Returns the picked one's full path, or None if the user quit. With
    keys (e.g. 'n'), keys that end picking too: it returns (the key, '' for Enter; the picked or
    selected one's full path), or None. twice_keys, excluded (relpaths): as pick_from_tree()'s."""
    args = [] if max_depth is None else ['--max-depth', str(max_depth)]
    for path in excluded:
        args += ['--exclude', path]
    if dirs_only:
        args.append('--dirs-only')
    if lazy:
        args.append('--lazy')
    picked = _run(args + _header_args(header) + _keys_args(keys, twice_keys) + _help_args(key_hints, ()) +
                  [dirpath], None)
    if picked is None:
        return None
    key, picked = _key_and_selected(keys, picked, twice_keys)
    path = dirpath if picked[0] == '.' else os.path.join(dirpath, picked[0])
    return (key, path) if keys or twice_keys else path


def _tree_paths(tree, excluded=()):
    """The tree's nodes' paths for treepicker (relative, '/'-separated), each dir before what's in
    it, siblings sorted by name, each after its type for --typed ('f ' a file, 'd ' a dir). The root
    isn't one: it's treepicker's root."""
    stack = list(reversed(_sorted_children(tree, tree.root)))
    while stack:
        node = stack.pop()
        if node.identifier in excluded:
            continue
        kind = 'f' if isinstance(node.data, entries.FileEntry) else 'd'
        yield '%s %s' % (kind, node.identifier)
        stack.extend(reversed(_sorted_children(tree, node.identifier)))


def _sorted_children(tree, identifier):
    return sorted(tree.children(identifier), key=lambda node: node.tag)
