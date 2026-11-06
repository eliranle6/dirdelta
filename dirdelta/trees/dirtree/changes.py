"""Removing and moving a tree's files, in batches, and what each kind of tree does for one file"""
from dirdelta.trees.dirtree.common import batch_verb
from dirdelta.ui import messages
from dirdelta.util import dryrun


class Changes(object):
    """Removals and moves (DirTree's)"""

    def remove_files(self, file_entries):
        """Remove the files, and drop them from the tree (so the next diff doesn't list them). A dry
        run changes neither."""
        verb = batch_verb('removing')
        nr_started = nr_removed = 0

        def starting(what, nr_files=1):
            """Say that removing what starts: a file, or e.g. a folder of nr_files of the files"""
            nonlocal nr_started
            nr_started += nr_files
            messages.print_line("%s %s (%d out of %d)" % (verb, what, nr_started, len(file_entries)))

        def removed(nr_files=1):
            nonlocal nr_removed
            nr_removed += nr_files

        self._batch(lambda: self._remove_files(file_entries, starting, removed),
                    ('Remove', 'removed', 'removes', 'from ' + self.displayname() + self.REMOVED_TO),
                    lambda: nr_removed, len(file_entries), dry_where='from ' + self.displayname())

    def move_files(self, moves, to=None):
        """Move files within the tree, or to another of its kind (to; a rename there too): each of
        moves is (relpath, new_relpath); a whole dir's, as one (see dir_moves()). Returns the moves
        done. A dry run changes nothing (and returns none)."""
        verb = batch_verb('moving')
        done = []
        to = to or self
        dir_moves, file_moves = self.dir_moves(moves, to)

        def work():
            for dirpath, new_dirpath, its_moves in dir_moves:
                messages.print_line("%s dir %s/ to %s/, with its %d files" % (verb, dirpath, new_dirpath,
                                                                             len(its_moves)))
                if not dryrun.DRYRUN and self._move_dir(dirpath, new_dirpath, to):
                    done.extend(its_moves)
            for number, (relpath, new_relpath) in enumerate(file_moves, 1):
                messages.print_line("%s %s to %s (%d out of %d)" % (verb, relpath, new_relpath, number,
                                                                    len(file_moves)))
                if not dryrun.DRYRUN and self._move_file(relpath, new_relpath, to):
                    done.append((relpath, new_relpath))

        def after():
            if done:
                self._moved(done)
        self._batch(work, ('Move', 'moved', 'moves', self._where(to)), lambda: len(done), len(moves), after=after)
        return done

    def _where(self, to):
        """Where a move or copy goes, to say it"""
        return 'in ' + self.displayname() if to is self else 'to ' + to.displayname()

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files (see _remove_file()), or in a dry run only say so, calling
        starting(what, nr_files) as removing each one (or some together) starts, and
        removed(nr_files) for those removed. One at a time, unless a tree does it otherwise."""
        for file_entry in file_entries:
            starting(file_entry)
            if dryrun.DRYRUN or self._remove_file(file_entry):
                removed()

    def copy_notes(self, relpaths):
        """Lines for the confirmation of copying the files at relpaths out of this tree"""
        return []

    def removal_notes(self, relpaths):
        """Lines for the confirmation of removing the files at relpaths"""
        return []

    def cant_fetch(self, relpath):
        """Why the file at relpath can't be copied out (fetch_file()), or None if it can"""
        return None

    def _copy_file(self, file_entry, source):
        """Copy file_entry (of another tree, from source, if given) into this tree, at the same
        relative path. Returns whether it was copied."""
        raise NotImplementedError("Can't copy files to %s" % (self.displayname(),))

    def _remove_file(self, file_entry):
        """Remove file_entry, and its node. Returns whether it was removed."""
        raise NotImplementedError("Can't remove files from %s" % (self.displayname(),))

    def _move_file(self, relpath, new_relpath, to=None):
        """Move the file at relpath to new_relpath here, or in to, another tree of its kind (where
        there's none), and its node. Returns whether it was moved (if not, says why)."""
        raise NotImplementedError("Can't move files in %s" % (self.displayname(),))
