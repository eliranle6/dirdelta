"""The tree beside a file picker (picker.Side): another replica's dirs and files, to look through
while picking, e.g. the sorted tree an inbox's files go to (Enter there moves them into the dir), or
the replica a sync copies to (to see whether it has a newer version of a file)."""
import subprocess

from dirdelta import entries
from dirdelta import paths


def items(path, tree=None, excluded=None):
    """The replica at path's dirs and files, as picker.Side's items ('d DIR', 'f FILE', relpaths in
    it, each dir before what's in it): a local dir's as find lists them (all of it, at once), a
    Drive one's from tree (its CloudDirTree, from the cache). excluded: a dir (relpath) left out,
    with all in it (e.g. an inbox in the sorted tree)."""
    if paths.is_cloud_path(path):
        assert tree is not None, "a Drive replica's tree is needed"
        found = []
        for node in sorted(tree.all_nodes(), key=lambda node: node.identifier.split('/')):
            if not node.identifier:
                continue
            kind = 'd' if isinstance(node.data, entries.DirEntry) else 'f'
            found.append('%s %s' % (kind, node.identifier))
    else:
        result = subprocess.run(['find', path, '-mindepth', '1', '(', '-type', 'd', '-printf', 'd %P\\0', ')',
                                 '-o', '(', '-type', 'f', '-printf', 'f %P\\0', ')'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        found = [item for item in result.stdout.decode('utf-8', 'surrogateescape').split('\0') if item]
        # Each dir's together, its dirs and files by name (find's order is the disk's)
        found.sort(key=lambda item: item[2:].split('/'))
    if excluded:
        found = [item for item in found if not (item[2:] == excluded or item[2:].startswith(excluded + '/'))]
    return found
