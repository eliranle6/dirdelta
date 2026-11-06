"""Who a tree tells of its changes, and the dirs it keeps"""
from dirdelta.trees.dirtree.common import _is_at_or_under


class Listeners(object):
    """A tree's listeners and kept dirs (DirTree's)"""

    def add_listener(self, listener):
        """From now on, listener is told of each file dirdelta makes, removes or moves here: its
        add(relpath, size), remove(relpath) and move(relpath, new_relpath) are called (e.g. an
        elsewhere.Index's), once it's done; not in a dry run"""
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    def _tell_added(self, relpath):
        if self._listeners:
            size = self.file_size(relpath)
            for listener in self._listeners:
                listener.add(relpath, size)

    def _tell_removed(self, relpath):
        for listener in self._listeners:
            listener.remove(relpath)

    def _tell_moved(self, relpath, new_relpath, to):
        """The file was moved to new_relpath in to (maybe this tree)"""
        if to is self:
            for listener in self._listeners:
                listener.move(relpath, new_relpath)
        else:
            self._tell_removed(relpath)
            to._tell_added(new_relpath)

    def keep_dirs(self, relpaths):
        """Never remove the dirs at relpaths when a removal or a move leaves them empty, nor move
        or remove one, or a dir it's in, as a whole (e.g. an inbox, whose files are moved out of it)"""
        self._kept_dirs |= set(relpaths)

    def _is_kept(self, dirpath):
        """Whether the dir at dirpath is kept, or has a kept dir in it"""
        return any(_is_at_or_under(kept, dirpath) for kept in self._kept_dirs)
