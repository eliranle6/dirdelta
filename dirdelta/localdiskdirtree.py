import collections
import contextlib
import errno
import hashlib
import os
import shutil
import subprocess

from dirdelta import dirtree
from dirdelta import dryrun
from dirdelta import entries
from dirdelta import exif
from dirdelta import hashcache
from dirdelta import localscan
from dirdelta import messages
from dirdelta import text


# How many of a listing's error messages a scan warning lists
MAX_SCAN_ERRORS_SHOWN = 3
# How much of a file content_hash() reads at a time (asking should_stop() after each)
HASH_READ_SIZE = 1 << 20


def factory(filesystem_dirpath, max_depth=None, silent=False):
    dirtree = LocalDiskDirTree(filesystem_dirpath, silent, max_depth)
    dirtree.update_from_filesystem()
    return dirtree


def is_local(tree):
    """Whether the tree is a local replica's (else, e.g., a Drive one's)"""
    return isinstance(tree, LocalReplica)


def scan_warning(where, errors):
    """A warning's lines if scanning where (a dir, or a description of dirs) couldn't read everything,
    given find's error messages, since then a diff may list files as missing that are there, or
    miss some; no lines if there are no errors."""
    if not errors:
        return []
    lines = ["Couldn't read everything in %s (%s), so the diff may be wrong:" %
             (where, text.counted(len(errors), 'error'))]
    return lines + text.listed(["  " + error for error in errors], MAX_SCAN_ERRORS_SHOWN)


class LocalReplica(dirtree.DirTree):
    """A local dir, whose files are asked of the disk, not of a tree of them (it has none: dirdiff
    diffs two local dirs, and an inbox's are listed): what it says is as things are now. What keeps a
    tree too is LocalDiskDirTree, told of each change by _file_added() and the like; what listens
    (see DirTree.add_listener()) is told by them."""
    def __init__(self, filesystem_dirpath, silent=True, max_depth=None):
        """Down to max_depth levels below it"""
        filesystem_dirpath = os.path.realpath(filesystem_dirpath)
        super(LocalReplica, self).__init__(rootpath=filesystem_dirpath, silent=silent)
        self.max_depth = max_depth
        # What a listing couldn't read in the last scan (see LocalDiskDirTree), so a tree may lack
        self.scan_errors = []
        # {relpath: (size, mtime_ns)} of its files, as of the last scan (None: not scanned), so
        # its hashing job needn't list them again (hashing.Job.scan())
        self.file_stamps = None
        # Whether removing a file moves it to the desktop's trash (see trashing())
        self._is_trashing = False

    def _file_added(self, relpath):
        """A file was just made at relpath"""
        self._tell_added(relpath)

    def _file_removed(self, relpath):
        """The file at relpath was just removed"""
        self._tell_removed(relpath)

    def _file_moved(self, relpath, new_relpath):
        """The file at relpath was just moved to new_relpath, in this tree"""
        self._tell_moved(relpath, new_relpath, self)

    def _dir_removed(self, relpath):
        """The (empty) dir at relpath was just removed"""

    def _dir_moved(self, dirpath, new_dirpath, to):
        """The dir at dirpath was just moved, with all in it, to new_dirpath in to (maybe this one)"""
        if self._listeners or to._listeners:
            for new_relpath in to.files_under(new_dirpath):
                if to.has_file(new_relpath):
                    self._tell_moved(dirpath + new_relpath[len(new_dirpath):], new_relpath, to)

    @contextlib.contextmanager
    def trashing(self):
        """Inside, removing a file moves it to the desktop's trash (gio trash), where it can be
        restored from, rather than removing it for good"""
        self._is_trashing = True
        self.REMOVED_TO = " (to the trash)"
        try:
            yield
        finally:
            self._is_trashing = False
            del self.REMOVED_TO

    def rescan(self):
        """See what's on disk now: it's asked anyway, so only whether it's there. Raises OSError if the
        dir isn't there anymore (e.g. it was unmounted)."""
        if not os.path.isdir(self._rootpath):
            raise OSError("%s isn't there anymore" % (self._rootpath,))
        self.scan_errors = []

    def file_size(self, relpath):
        try:
            return os.lstat(os.path.join(self._rootpath, relpath)).st_size
        except OSError:
            return None

    def date_taken(self, relpath):
        return exif.date_taken(os.path.join(self._rootpath, relpath))

    def modified_time(self, relpath):
        try:
            return os.lstat(os.path.join(self._rootpath, relpath)).st_mtime
        except OSError:
            return None

    def local_path(self, relpath):
        return os.path.join(self._rootpath, relpath)

    def known_hash(self, relpath, algorithm):
        return hashcache.get(os.path.join(self._rootpath, relpath), algorithm)

    def content_hash(self, relpath, algorithm, should_stop=None):
        return self.content_hashes(relpath, [algorithm], should_stop)[algorithm]

    def content_hashes(self, relpath, algorithms, should_stop=None):
        # From the hash cache, if it has them (and the file didn't change); the others all in one
        # read of the file, then kept there
        path = os.path.join(self._rootpath, relpath)
        found = {algorithm: hashcache.get(path, algorithm) for algorithm in algorithms}
        needed = [algorithm for algorithm, value in found.items() if value is None]
        if not needed:
            return found
        digests = {algorithm: hashlib.new(algorithm) for algorithm in needed}
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(HASH_READ_SIZE), b''):
                    if should_stop is not None and should_stop():
                        raise dirtree.HashStopped()
                    for digest in digests.values():
                        digest.update(chunk)
        except OSError:
            return found
        computed = {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}
        hashcache.put(path, computed)
        return dict(found, **computed)

    def has_file(self, relpath):
        return os.path.isfile(os.path.join(self._rootpath, relpath))

    def files_by_name(self, progress=None):
        """As DirTree's, but from a listing of the dir (down to max_depth levels), with its files'
        sizes. If progress raises, the listing is stopped."""
        found = collections.defaultdict(list)
        for relpath, (size, _) in localscan.scan(self._rootpath, self.max_depth, progress).files().items():
            found[os.path.basename(relpath)].append((relpath, size))
        return found

    def _copy_file(self, file_entry, source):
        reason = source.cant_fetch(file_entry.relpath) if source is not None else None
        if reason is not None:
            messages.print_line("Skipped %s: %s" % (file_entry.relpath, reason), "yellow")
            return False
        dest_path = os.path.join(self._rootpath, file_entry.relpath)
        did_dest_exist = os.path.exists(dest_path)
        try:
            dest_dirpath = os.path.dirname(dest_path)
            if os.path.exists(dest_dirpath):
                assert os.path.isdir(dest_dirpath)
            else:
                try:
                    os.makedirs(dest_dirpath)
                except OSError as ex:
                    messages.print_line("Copy failed: %s" % (str(ex),), "red")
                    return False
            if source is not None:
                source.fetch_file(file_entry.relpath, dest_path)
            else:
                self._copy_local_file_to_tree_with_path(file_entry.full_filesystem_path(), dest_path)
        except OSError as ex:
            messages.print_line("Copy failed: %s" % (str(ex),), "red")
            self._drop_copy(dest_path, did_dest_exist)
            return False
        except BaseException:
            self._drop_copy(dest_path, did_dest_exist)
            raise
        self._file_added(file_entry.relpath)
        return True

    def _drop_copy(self, dest_path, did_dest_exist):
        """Undo a copy that failed or was cut off (e.g. by Ctrl-C), if it started: a copy cut off in
        the middle leaves part of the file, dropped unless it's a file that was there before"""
        if not did_dest_exist and os.path.exists(dest_path):
            os.unlink(dest_path)

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files, and then the dirs that removing them left empty"""
        super(LocalReplica, self)._remove_files(file_entries, starting, removed)
        if not dryrun.DRYRUN:
            self._remove_emptied_dirs(file_entries)

    def _remove_emptied_dirs(self, file_entries):
        """Remove the dirs of the (removed) files that are empty, and the dirs they're in that this
        leaves empty, up to (not including) the root. Only empty ones: rmdir fails on one with
        anything in it, which is then kept, as are the dirs it's in."""
        nr_removed = 0
        dirpaths = {os.path.dirname(file_entry.full_filesystem_path()) for file_entry in file_entries}
        # The deepest first, so a dir's emptied subdirs are gone when it's tried
        for dirpath in sorted(dirpaths, key=lambda dirpath: dirpath.count(os.sep), reverse=True):
            while (dirpath.startswith(self._rootpath.rstrip(os.sep) + os.sep) and
                   os.path.relpath(dirpath, self._rootpath) not in self._kept_dirs):
                try:
                    os.rmdir(dirpath)
                except OSError:
                    break
                nr_removed += 1
                self._dir_removed(os.path.relpath(dirpath, self._rootpath))
                dirpath = os.path.dirname(dirpath)
        if nr_removed:
            messages.print_line("Removed %d dirs left empty" % (nr_removed,))

    def removal_notes(self, relpaths):
        return ["Dirs left empty are removed too."]

    def files_under(self, dirpath):
        # A symlink to a dir is one too, so a dir with one isn't moved whole (it isn't one of the moves).
        path = os.path.join(self._rootpath, dirpath)
        if not dirpath or os.path.islink(path) or not os.path.isdir(path):
            return []
        found = []
        for walked, dirnames, filenames in os.walk(path):
            relative = os.path.relpath(walked, self._rootpath)
            found += [os.path.join(relative, name) for name in filenames]
            found += [os.path.join(relative, name) for name in dirnames
                      if os.path.islink(os.path.join(walked, name))]
        return found

    def exists(self, relpath):
        return os.path.lexists(os.path.join(self._rootpath, relpath))

    def cant_change(self, relpath):
        if not os.access(os.path.dirname(os.path.join(self._rootpath, relpath)), os.W_OK):
            return "it's on a read-only dir"
        return None

    def _is_stuck(self, relpath, path):
        """Whether what's at path can't leave its dir, as it's read-only (said): between filesystems, a
        move is a copy then a removal, which would fail only after the copy was made"""
        if os.access(os.path.dirname(path), os.W_OK):
            return False
        messages.print_line("Skipped %s: it's on a read-only dir, so it can only be copied" % (relpath,), "yellow")
        return True

    def _move_dir(self, dirpath, new_dirpath, to=None):
        to = to or self
        path = os.path.join(self._rootpath, dirpath)
        new_path = os.path.join(to.fullpath(), new_dirpath)
        if self._is_stuck(dirpath, path):
            return False
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s/: %s is there already" % (dirpath, new_dirpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            _rename(path, new_path)
        except OSError as error:
            messages.print_line("Move failed: %s" % (error,), "red")
            return False
        # Its files' hashes, under their new paths (between filesystems, a copy may have other times,
        # and then they're hashed again)
        hashcache.move(path, new_path)
        self._dir_moved(dirpath, new_dirpath, to)
        # The dirs it was in, if it leaves them empty, as a removal does
        self._remove_emptied_dirs([entries.FileEntry(os.path.basename(dirpath), dirpath, path)])
        return True

    def _move_file(self, relpath, new_relpath, to=None):
        to = to or self
        path = os.path.join(self._rootpath, relpath)
        new_path = os.path.join(to.fullpath(), new_relpath)
        if self._is_stuck(relpath, path):
            return False
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s: %s is there already" % (relpath, new_relpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            _rename(path, new_path)
        except OSError as error:
            messages.print_line("Move failed: %s" % (error,), "red")
            return False
        hashcache.move(path, new_path)
        if to is self:
            self._file_moved(relpath, new_relpath)
        else:
            self._file_removed(relpath)
            to._file_added(new_relpath)
        # As a removal does
        self._remove_emptied_dirs([entries.FileEntry(os.path.basename(relpath), relpath, path)])
        return True

    def _remove_file(self, file_entry):
        try:
            if self._is_trashing:
                result = subprocess.run(['gio', 'trash', file_entry.full_filesystem_path()],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
                if result.returncode != 0:
                    raise OSError(result.stdout.strip() or "gio trash failed")
            else:
                os.unlink(file_entry.full_filesystem_path())
        except OSError as error:
            # Said, and the others go on (it's kept, in the tree too)
            messages.print_line("Remove failed: %s" % (error,), "red")
            return False
        self._file_removed(file_entry.relpath)
        return True

    def _copy_within(self, relpath, new_relpath, to=None):
        to = to or self
        new_path = os.path.join(to.fullpath(), new_relpath)
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s: %s is there already" % (relpath, new_relpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            self._copy_local_file_to_tree_with_path(os.path.join(self._rootpath, relpath), new_path)
        except OSError as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        to._file_added(new_relpath)
        return True

    def fetch_file(self, relpath, local_path):
        self._copy_local_file_to_tree_with_path(os.path.join(self._rootpath, relpath), local_path)

    def _copy_local_file_to_tree_with_path(self, src, dst):
        # copy2: with its modification time, rather than the copy's
        shutil.copy2(src, dst)
        # The copy's hashes are the file's, if they're known (so it isn't read again to hash it)
        hashes = hashcache.get_all(src)
        if hashes:
            hashcache.put(dst, hashes)


class LocalDiskDirTree(LocalReplica):
    """A LocalReplica with a tree of its files too (which is empty until update_from_filesystem(), which
    scans down to max_depth levels below it), as a diff with a Drive replica's tree needs"""
    def update_from_filesystem(self):
        """Add the dirs and files on disk (hidden ones too), down to max_depth levels below the root."""
        if not self._silent:
            messages.print_line("Scanning directory %s..." % (self._rootpath,))
        scan = localscan.scan(self._rootpath, self.max_depth)
        self.scan_errors = scan.errors
        for relpath, (kind, _, _) in scan.entries.items():
            if kind == localscan.FILE:
                self.add_file_by_relpath(relpath)
            else:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
        self.file_stamps = scan.files()

    def rescan(self):
        """See what's on disk now: the tree is replaced only once the new scan is done, so it's as it
        was if it's stopped. Raises OSError if the dir isn't there anymore (e.g. it was unmounted), and
        then too."""
        super(LocalDiskDirTree, self).rescan()
        scanned = LocalDiskDirTree(self._rootpath, True, self.max_depth)
        scanned.update_from_filesystem()
        is_trashing, silent, listeners = self._is_trashing, self._silent, self._listeners
        self.__dict__.update(scanned.__dict__)
        self._is_trashing, self._silent, self._listeners = is_trashing, silent, listeners

    def _file_added(self, relpath):
        self.add_file_by_relpath(relpath)
        super(LocalDiskDirTree, self)._file_added(relpath)

    def _file_removed(self, relpath):
        if relpath in self:
            self.remove_node(relpath)
        super(LocalDiskDirTree, self)._file_removed(relpath)

    def _file_moved(self, relpath, new_relpath):
        if relpath in self:
            self.remove_node(relpath)
            self.add_file_by_relpath(new_relpath)
        super(LocalDiskDirTree, self)._file_moved(relpath, new_relpath)

    def _dir_removed(self, relpath):
        if relpath in self:
            self.remove_node(relpath)

    def _dir_moved(self, dirpath, new_dirpath, to):
        super(LocalDiskDirTree, self)._dir_moved(dirpath, new_dirpath, to)
        if isinstance(to, LocalDiskDirTree):
            self._move_subtree(dirpath, new_dirpath, to)
        elif dirpath in self:
            self.remove_node(dirpath)


def _rename(path, new_path):
    """Move path to new_path: a rename, or between filesystems (which a rename can't), a copy and a
    removal"""
    try:
        os.rename(path, new_path)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(path, new_path)
