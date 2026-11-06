"""The sorted tree beside the inbox's picker (see sidetree.py), and its hashing"""
import os
import posixpath

from dirdelta.hashes import hashcache
from dirdelta.inbox.formatting import _join
from dirdelta.known import replicas
from dirdelta.screens import hashes_screen
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree
from dirdelta.ui import messages
from dirdelta.util import dryrun
from dirdelta.sync import replica_ops


class Side(object):
    """The tree beside the picker (InboxSort's)"""

    # The sorted tree beside the inbox's picker (see sidetree.py)

    def _side_items(self):
        """The sorted tree's dirs and files, for the tree beside the picker, but the inbox's, if
        it's in it"""
        return self._side_listing.items()

    def _read_inbox_anew(self, relpath):
        """Ctrl-R: the inbox (on Drive, its folder of relpath), and the sorted tree too if both are local"""
        self._read_anew(self._inbox_tree, self._inbox_index, self.inbox_is_cloud, relpath)
        if not self.inbox_is_cloud and not self.root_is_cloud:
            self._read_anew(self._root_tree, self._root_index, False, '')

    def _read_side_anew(self, relpath):
        """Ctrl-R in the sorted tree beside the picker: it (on Drive, its folder of relpath)"""
        self._read_anew(self._root_tree, self._root_index, self.root_is_cloud, relpath)

    def _read_anew(self, tree, index, is_cloud, relpath):
        """What's known of the replica of tree and index, read anew when next needed (a local one's is
        asked of its disk; a Drive one's folder of relpath is read now), if it could be"""
        if is_cloud:
            with self._drive_lock:
                if not replica_ops.refresh_replica(tree, relpath):
                    return
        elif not replica_ops.rescan_replica(tree):
            return
        index.invalidate()
        # Its files may have other contents now
        self._checked.clear()
        if tree is self._root_tree:
            # Built again, in the background (see _start_indexing())
            self._indexing = None
        # (A local one's isn't listed again for another's folder read from Drive)
        if tree is self._root_tree or self.root_is_cloud:
            self._side_listing.invalidate()
        for job in hashes_screen.jobs_of([tree]):
            if tree is self._root_tree:
                hashes_screen.scan_with_listing(job, self._side_listing)
            else:
                job.scan_in_background()

    def _warn_if_not_all_read(self):
        """Say so if the inbox or the sorted tree couldn't all be listed, as a sync does: what can't be
        read isn't shown"""
        lines = (localdiskdirtree.scan_warning(self.inbox_path, getattr(self._inbox_tree, 'scan_errors', []),
                                               "its list lacks what's there") +
                 localdiskdirtree.scan_warning(self.root_path, self._side_listing.errors, "its list lacks what's there"))
        if lines:
            messages.show("Warning: couldn't read everything", lines, dryrun.label(), 'yellow')

    def _side_follow(self, relpath):
        """Where in the sorted tree the inbox's file at relpath is related to (for the tree beside
        the picker to show, while it's selected): Claude's dir for it, or else where a copy of it
        is, or else a file of its name; None for none (or a dir)"""
        recommendation = self._recommendations.get(relpath)
        target = self._target(relpath) if recommendation else None
        if target is not None:
            return posixpath.dirname(target)
        copies = self._copies(relpath)
        if copies:
            return copies[0]
        if self._root_index.is_built():
            named = self._root_index.files_named(posixpath.basename(relpath))
            if named:
                return sorted(named)[0]
        return None

    def _move_to_side(self, relpaths, side_relpath):
        """Move the inbox's files at relpaths into the sorted tree's dir at side_relpath (or the dir
        of the file there), Enter's in the sorted tree beside the picker, once the user confirms (see
        _approve()). Returns the ones moved, as _act() does."""
        if not relpaths:
            return None
        cant = self._cant_be_done()
        if self.COPY_TO in cant:
            messages.show("Read-only", ["%s is read-only: no files can go into it." % (self.root_path,)], dryrun.label(), 'yellow')
            return None
        destination = side_relpath if self._is_sorted_dir(side_relpath) else posixpath.dirname(side_relpath)
        destination = self._not_the_inbox(destination)
        if destination is None:
            return None
        # From a read-only inbox they can only be copied (its confirmation says which)
        done = self._approve(self.COPY_TO if self.MOVE_TO in cant else self.MOVE_TO,
                             [(relpath, _join(destination, posixpath.basename(relpath))) for relpath in relpaths])
        if done and self._known_replicas is not None:
            self._known_replicas.record_dir(self.root_path, destination)
            replicas.save(self._known_replicas)
        return done

    def _is_sorted_dir(self, relpath):
        """Whether the sorted tree's relpath is a dir (the root too)"""
        if not relpath:
            return True
        if self.root_is_cloud:
            node = self._root_tree.get_node(relpath)
            return node is not None and isinstance(node.data, entries.DirEntry)
        return os.path.isdir(os.path.join(self.root_path, relpath))

    def _trees(self):
        return [self._inbox_tree, self._root_tree]

    def _jobs(self):
        """The hashing jobs of the inbox and the sorted tree, the local ones (see hashing.py)"""
        return hashes_screen.jobs_of(self._trees())

    def prepare_hashing(self):
        """Look for the hashes of the local inbox's and sorted tree's files, and offer to hash the
        rest (see hashes_screen.offer()). Returns whether to go on. A local sorted tree's hashes are
        kept in it (see hashcache.use_replica()); the inbox's, if it's not in it, aren't (it's no
        replica)."""
        if not self.root_is_cloud:
            hashcache.use_replica(self.root_path)
        return hashes_screen.offer(hashes_screen.prepare(self._trees()))
