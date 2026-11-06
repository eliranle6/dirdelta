"""Copying files into a tree, and within it"""
import contextlib

from dirdelta.trees.dirtree.common import _verb
from dirdelta.ui import messages
from dirdelta.util import dryrun


class Copying(object):
    """Copies (DirTree's)"""

    def copy_inner_entries_from_dirtree(self, dirtree, source=None):
        """copy_in() dirtree's files"""
        self.copy_in(list(dirtree.iter_files()), source)

    def copy_in(self, files, source=None):
        """Copy files (FileEntry's) into this tree's dir, each at its relpath, and add them to the
        tree (so the next diff doesn't list them): from source (a tree, by its fetch_file()), or
        else from their entries' full paths on the local disk (which may be elsewhere than at their
        relpaths, e.g. an inbox's files going to other dirs). A dry run changes neither."""
        files = list(files)
        # In a dry run nothing changes: no files or dirs, and not the tree
        verb = _verb('copying')
        nr_started = nr_copied = 0

        def starting(file_entry):
            nonlocal nr_started
            nr_started += 1
            messages.print_line("%s %s (%d out of %d)" % (verb, file_entry, nr_started, len(files)))

        def copied(is_copied):
            nonlocal nr_copied
            nr_copied += bool(is_copied)

        def work():
            if dryrun.DRYRUN:
                for file_entry in files:
                    starting(file_entry)
                    copied(True)
            else:
                self._copy_files(files, source, starting, copied)
        self._batch(work, ('Copy', 'copied', 'copies', 'to ' + self.displayname()), lambda: nr_copied, len(files))

    @contextlib.contextmanager
    def replacing(self):
        """Inside, copy_in() replaces a file the tree has already at a copy's path (another version
        of it, see differing.py), as a tree of its kind can: a local dir's goes to the desktop's trash,
        a Drive file gets the copy as its new version (Drive keeps the old one). Outside, a tree
        doesn't expect one there."""
        self._is_replacing = True
        try:
            yield
        finally:
            self._is_replacing = False

    def copy_files_within(self, copies, to=None):
        """Copy files within the tree, or to another of its kind (to): each of copies is (relpath,
        new_relpath). Returns the copies done. A dry run changes nothing (and returns none)."""
        verb = _verb('copying')
        done = []
        to = to or self

        def work():
            for number, (relpath, new_relpath) in enumerate(copies, 1):
                messages.print_line("%s %s to %s (%d out of %d)" % (verb, relpath, new_relpath, number,
                                                                    len(copies)))
                if not dryrun.DRYRUN and self._copy_within(relpath, new_relpath, to):
                    done.append((relpath, new_relpath))
        self._batch(work, ('Copy', 'copied', 'copies', self._where(to)), lambda: len(done), len(copies))
        return done

    def _batch(self, work, words, nr_done, total, after=None, dry_where=None):
        """Run a batch operation's work(), which Ctrl-C stops (it's said, see messages.note_stopped()),
        then after() (if given), then say how it ended, by words: (its noun, its past, its third
        person, where, e.g. ('Copy', 'copied', 'copies', 'to cloud/x')), nr_done() files of total
        (or in a dry run, that nothing was, where dry_where says, if given)"""
        noun, past, third, where = words
        is_stopped = False
        try:
            work()
        except KeyboardInterrupt:
            messages.note_stopped()
            is_stopped = True
        if after is not None:
            after()
        ended = "stopped" if is_stopped else "complete"
        if dryrun.DRYRUN:
            messages.print_line("Dry run %s: nothing was %s %s (DRYRUN=0 %s)" % (ended, past, dry_where or where, third))
        else:
            messages.print_line("%s %s: %s %d of %d files %s" % (noun, ended, past, nr_done(), total, where))

    def _copy_within(self, relpath, new_relpath, to=None):
        """Copy the file at relpath to new_relpath here, or in to, another tree of its kind (where
        there's none), and add its node. Returns whether it was copied (if not, says why)."""
        raise NotImplementedError("Can't copy files within %s" % (self.displayname(),))

    def _copy_files(self, files, source, starting, copied):
        """Copy the files (see _copy_file()), calling starting(file_entry) as each one's copy
        starts, and copied(whether it was copied) as it ends. One at a time, unless a tree does it
        otherwise."""
        for file_entry in files:
            starting(file_entry)
            copied(self._copy_file(file_entry, source))
