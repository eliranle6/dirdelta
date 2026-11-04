"""The tree beside a file picker (picker.Side): another replica's dirs and files, to look through
while picking, e.g. the sorted tree an inbox's files go to (Enter there moves them into the dir), or
the replica a sync copies to (to see whether it has a newer version of a file)."""
from dirdelta import entries
from dirdelta import localscan
from dirdelta import paths


def items(path, tree=None, excluded=None):
    """The replica at path's dirs and files, as picker.Side's items ('d DIR', 'f FILE', relpaths in
    it, each dir before what's in it): a local dir's as it's listed now (all of it, at once), a
    Drive one's from tree (its CloudDirTree, from the cache). excluded: a dir (relpath) left out,
    with all in it (e.g. an inbox in the sorted tree)."""
    return _listed(path, tree, excluded)[0]


def _listed(path, tree, excluded):
    """(items(), what couldn't be read of it, a local dir's files as {relpath: (size, mtime_ns)})"""
    errors, files = [], None
    if paths.is_cloud_path(path):
        assert tree is not None, "a Drive replica's tree is needed"
        found = []
        for node in sorted(tree.all_nodes(), key=lambda node: node.identifier.split('/')):
            if not node.identifier:
                continue
            kind = 'd' if isinstance(node.data, entries.DirEntry) else 'f'
            found.append('%s %s' % (kind, node.identifier))
    else:
        # As deep as the replica's other listings go: what's below them isn't compared
        scan = localscan.scan(path, getattr(tree, 'max_depth', None))
        errors, files = scan.errors, scan.files()
        found = ['%s %s' % (kind, relpath) for relpath, (kind, _, _) in scan.entries.items()]
        # Each dir's together, its dirs and files by name (find's order is the disk's)
        found.sort(key=lambda item: item[2:].split('/'))
    # What dirdelta keeps in a replica isn't one of its files
    found = [item for item in found if not paths.is_meta(item[2:])]
    if excluded:
        found = [item for item in found if not paths.is_at_or_under(item[2:], excluded)]
    return found, errors, files


class Listing(object):
    """items() of a replica, kept between its picker's showings (listing a big one takes seconds), until
    it changes: its tree tells it what dirdelta changes there (see DirTree.add_listener()), and invalidate()
    says what the tree doesn't (a folder read anew from Drive, an empty dir renamed, Ctrl-R pressed). What
    changes outside dirdelta is seen then, or the next time its picker is entered."""
    def __init__(self, path, tree, excluded=None):
        self._path, self._tree, self._excluded = path, tree, excluded
        self.max_depth = getattr(tree, 'max_depth', None)
        self._items = None
        # What couldn't be read of it, when it was last listed
        self.errors = []
        # Told of the next listing's files (see invalidate())
        self._on_listed = None
        tree.add_listener(self)

    def items(self):
        if self._items is None:
            self._items, self.errors, files = _listed(self._path, self._tree, self._excluded)
            self._tell_listed(files)
        return self._items

    def invalidate(self, on_listed=None):
        """It's listed anew when next needed. on_listed(files): called then with its files, as
        {relpath: (size, mtime_ns)}, so what needs them too needn't list them; with None if it has none
        (it's on Drive), or it's closed before that."""
        self._items = None
        if on_listed is not None:
            self._on_listed = on_listed

    def _tell_listed(self, files):
        on_listed, self._on_listed = self._on_listed, None
        if on_listed is not None:
            on_listed(files)

    def close(self):
        """It's not needed anymore: its tree needn't tell it, and what it listed can go"""
        self._tree.remove_listener(self)
        self._items = None
        self._tell_listed(None)

    # What the tree tells it

    def add(self, relpath, size):
        self.invalidate()

    def remove(self, relpath):
        self.invalidate()

    def move(self, relpath, new_relpath):
        self.invalidate()
