"""Moving a whole dir as one, and what can't be changed"""
from dirdelta.trees import entries
from dirdelta.trees.dirtree.common import _is_at_or_under


class DirMoves(object):
    """Moving dirs (DirTree's)"""

    def dir_moves(self, moves, to=None):
        """Of moves (relpath, new_relpath), the ones that move a whole dir: [(dirpath, new_dirpath,
        its moves)], the topmost, each a dir all of whose files (files_under()) are moved into
        new_dirpath (in to, or here) at the same relative paths, where there's nothing yet; and the
        other moves"""
        to = to or self
        new_of = dict(moves)
        pairs = set()
        for relpath, new_relpath in moves:
            path, new_path = relpath.split('/'), new_relpath.split('/')
            # The dirs above both whose paths below them are the same
            depth = 1
            while depth < len(path) and depth < len(new_path) and path[-depth:] == new_path[-depth:]:
                pairs.add(('/'.join(path[:-depth]), '/'.join(new_path[:-depth])))
                depth += 1
        found = []
        for dirpath, new_dirpath in sorted(pairs, key=lambda pair: (pair[0].count('/'), pair)):
            if (any(_is_at_or_under(dirpath, other) for other, _, _ in found) or self._is_kept(dirpath) or
                    (to is self and (_is_at_or_under(new_dirpath, dirpath) or _is_at_or_under(dirpath, new_dirpath)))):
                continue
            files = self.files_under(dirpath)
            if (files and not to.exists(new_dirpath) and
                    all(new_of.get(relpath) == new_dirpath + relpath[len(dirpath):] for relpath in files)):
                found.append((dirpath, new_dirpath, [(relpath, new_of[relpath]) for relpath in files]))
        in_dirs = {relpath for _, _, its_moves in found for relpath, _ in its_moves}
        return found, [move for move in moves if move[0] not in in_dirs]

    def files_under(self, dirpath):
        """The relpaths of what's under the dir at dirpath that isn't a dir (none if it isn't one)"""
        node = self.get_node(dirpath)
        if node is None or not isinstance(node.data, entries.DirEntry):
            return []
        return [node.identifier for node in self._tree.subtree(dirpath).all_nodes_itr()
                if isinstance(node.data, entries.FileEntry)]

    def nodes_under(self, dirpath):
        """The nodes at and under dirpath (the dir's, and all in it), each before what's in it"""
        return list(self._tree.subtree(dirpath).all_nodes_itr())

    def exists(self, relpath):
        """Whether there's a file or dir at relpath"""
        return relpath in self

    def _move_dir(self, dirpath, new_dirpath, to=None):
        """Move the dir at dirpath, and all in it, to new_dirpath here, or in to, another tree of its
        kind (where there's nothing), and its nodes. Returns whether it was moved (if not, says why)."""
        raise NotImplementedError("Can't move dirs in %s" % (self.displayname(),))

    def _move_subtree(self, dirpath, new_dirpath, to=None):
        """Move the nodes at and under dirpath to new_dirpath, here or in to (if this tree has them).
        Returns the (relpath, new_relpath) of each."""
        to = to or self
        if dirpath not in self:
            return []
        nodes = [(node.identifier, isinstance(node.data, entries.FileEntry))
                 for node in self._tree.subtree(dirpath).all_nodes_itr()]
        self.remove_node(dirpath)
        moved = []
        # Each dir before what's in it
        for relpath, is_file in sorted(nodes, key=lambda node: node[0].count('/')):
            new_relpath = new_dirpath + relpath[len(dirpath):]
            if is_file:
                to.add_file_by_relpath(new_relpath)
            else:
                to.create_dir_node_from_relpath_if_not_exists(new_relpath)
            moved.append((relpath, new_relpath))
        return moved

    def _moved(self, moves):
        """After move_files() did the moves (relpath, new_relpath), e.g. to tidy the dirs they left"""

    def cant_change(self, relpath):
        """Why what's at relpath can't be moved or renamed in its dir, whatever it is, or None if it
        can (see cant_move())"""
        return None

    def cant_move(self, relpath):
        """Why the file at relpath can't be moved (move_files()), or None if it can"""
        return None

    def fetch_file(self, relpath, local_path):
        """Copy the file at relpath to local_path, on the local disk"""
        raise NotImplementedError("Can't copy files from %s" % (self.displayname(),))
