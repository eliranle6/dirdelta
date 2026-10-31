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
from dirdelta import hashing
from dirdelta import messages


# How many of find's error messages a scan warning lists
MAX_SCAN_ERRORS_SHOWN = 3
# How much of find's output files_by_name() reads at a time, at most
FIND_READ_SIZE = 1 << 16
# How much of a file content_hash() reads at a time (asking should_stop() after each)
HASH_READ_SIZE = 1 << 20


def factory(filesystem_dirpath, max_depth=None, silent=False):
    dirtree = LocalDiskDirTree(filesystem_dirpath, silent, max_depth)
    dirtree.update_from_filesystem()
    return dirtree


def scan_warning(where, errors):
    """A warning's lines if scanning where (a dir, or a description of dirs) couldn't read everything,
    given find's error messages, since then a diff may list files as missing that are there, or
    miss some; no lines if there are no errors."""
    if not errors:
        return []
    lines = ["find couldn't read everything in %s (%d errors), so the diff may be wrong:" %
             (where, len(errors))]
    lines += ["  " + error for error in errors[:MAX_SCAN_ERRORS_SHOWN]]
    if len(errors) > MAX_SCAN_ERRORS_SHOWN:
        lines.append("  (and %d more)" % (len(errors) - MAX_SCAN_ERRORS_SHOWN,))
    return lines


class LocalDiskDirTree(dirtree.DirTree):
    def __init__(self, filesystem_dirpath, silent, max_depth=None):
        """A tree of the dir, which is empty until update_from_filesystem(), which scans down to
        max_depth levels below it."""
        filesystem_dirpath = os.path.realpath(filesystem_dirpath)
        super(LocalDiskDirTree, self).__init__(rootpath=filesystem_dirpath, silent=silent)
        self.max_depth = max_depth
        # find's messages about what it couldn't read in the last scan, so the tree may lack
        self.scan_errors = []
        # {relpath: (size, mtime_ns)} of its files, as of the last scan (None: not scanned), so
        # its hashing job needn't list them again (hashing.Job.scan())
        self.file_stamps = None
        # Whether removing a file moves it to the desktop's trash (see trashing())
        self._is_trashing = False

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

    def update_from_filesystem(self):
        """Add the dirs and files on disk (hidden ones too), down to max_depth levels below the root."""
        if not self._silent:
            messages.print_line("Scanning directory %s..." % (self._rootpath,))
        # One find for both files and dirs, each entry its type letter, size, modification time and
        # path, ending with '\0' (paths may hold newlines). Other types (e.g. symlinks) are skipped.
        command = ["find", self._rootpath, "-mindepth", "1"]
        if self.max_depth is not None:
            command += ["-maxdepth", str(self.max_depth)]
        command += ["-printf", "%y %s %T@ %p\\0"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.scan_errors = result.stderr.decode('utf-8', 'surrogateescape').splitlines()
        stamps = {}
        prefix_length = len(self._rootpath.rstrip('/')) + 1
        for entry in result.stdout.split(b'\0'):
            if not entry:
                continue
            kind, size, mtime, path = entry.split(b' ', 3)
            # Names needn't be valid UTF-8: decoded like Python decodes paths
            path = os.fsdecode(path)
            if kind == b'f':
                self.add_file_by_fullpath(path)
                stamps[path[prefix_length:]] = (int(size), hashing.nanoseconds(mtime.decode('ascii')))
            elif kind == b'd':
                self.create_dir_node_from_fullpath_if_not_exists(path)
        self.file_stamps = stamps

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
        # On disk: the tree may not be scanned (see dirdiff.py)
        return os.path.isfile(os.path.join(self._rootpath, relpath))

    def files_by_name(self, progress=None):
        """As DirTree's, but from a find of the dir (down to max_depth levels), with its files'
        sizes: the tree may not be scanned (see dirdiff.py), or be from an older scan. Read as find
        goes, for progress; if progress raises, find is stopped."""
        command = ["find", self._rootpath, "-mindepth", "1"]
        if self.max_depth is not None:
            command += ["-maxdepth", str(self.max_depth)]
        command += ["-type", "f", "-printf", "%s %P\\0"]
        found = collections.defaultdict(list)
        count = 0
        # The start of an entry whose end hasn't been read yet
        pending = b''
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            for chunk in iter(lambda: process.stdout.read1(FIND_READ_SIZE), b''):
                items = (pending + chunk).split(b'\0')
                pending = items.pop()
                for item in items:
                    size, relpath = item.split(b' ', 1)
                    relpath = os.fsdecode(relpath)
                    found[os.path.basename(relpath)].append((relpath, int(size)))
                count += len(items)
                if progress is not None:
                    progress(count)
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.wait()
        return found

    def _copy_file(self, file_entry, source):
        reason = source.cant_fetch(file_entry.relpath) if source is not None else None
        if reason is not None:
            messages.print_line("Skipped %s: %s" % (file_entry.relpath, reason), "yellow")
            return False
        new_file_entry = self.add_file_by_relpath(file_entry.relpath)
        dest_path = new_file_entry.full_filesystem_path()
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
                    self.remove_node(new_file_entry.relpath)
                    return False
            if source is not None:
                source.fetch_file(file_entry.relpath, dest_path)
            else:
                self._copy_local_file_to_tree_with_path(file_entry.full_filesystem_path(), dest_path)
            return True
        except OSError as ex:
            messages.print_line("Copy failed: %s" % (str(ex),), "red")
            self._drop_copy(new_file_entry, dest_path, did_dest_exist)
            return False
        except BaseException:
            self._drop_copy(new_file_entry, dest_path, did_dest_exist)
            raise

    def _drop_copy(self, new_file_entry, dest_path, did_dest_exist):
        """Undo a copy that failed or was cut off (e.g. by Ctrl-C), if it started"""
        if new_file_entry.relpath in self:
            self.remove_node(new_file_entry.relpath)
        # A copy cut off in the middle leaves part of the file: drop it, unless it's a file that
        # was there before
        if not did_dest_exist and os.path.exists(dest_path):
            os.unlink(dest_path)

    def _remove_files(self, file_entries, starting, removed):
        """Remove the files, and then the dirs that removing them left empty"""
        super(LocalDiskDirTree, self)._remove_files(file_entries, starting, removed)
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
                relpath = os.path.relpath(dirpath, self._rootpath)
                if relpath in self:
                    self.remove_node(relpath)
                dirpath = os.path.dirname(dirpath)
        if nr_removed:
            messages.print_line("Removed %d dirs left empty" % (nr_removed,))

    def removal_notes(self, relpaths):
        return ["Dirs left empty are removed too."]

    def _files_under(self, dirpath):
        # On disk: the tree may not be scanned (see dirdiff.py). A symlink to a dir is one too, so a
        # dir with one isn't moved whole (it isn't one of the moves).
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

    def _exists(self, relpath):
        return os.path.lexists(os.path.join(self._rootpath, relpath))

    def _move_dir(self, dirpath, new_dirpath):
        path = os.path.join(self._rootpath, dirpath)
        new_path = os.path.join(self._rootpath, new_dirpath)
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
        self._move_subtree(dirpath, new_dirpath)
        # The dirs it was in, if it leaves them empty, as a removal does
        self._remove_emptied_dirs([entries.FileEntry(os.path.basename(dirpath), dirpath, path)])
        return True

    def _move_file(self, relpath, new_relpath):
        path = os.path.join(self._rootpath, relpath)
        new_path = os.path.join(self._rootpath, new_relpath)
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
        # The tree may not have it, if it wasn't scanned (see dirdiff.py)
        if relpath in self:
            self.remove_node(relpath)
            self.add_file_by_relpath(new_relpath)
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
        # The tree may not have it, if it wasn't scanned (see dirdiff.py)
        if file_entry.relpath in self:
            self.remove_node(file_entry.relpath)
        return True

    def _copy_within(self, relpath, new_relpath):
        new_path = os.path.join(self._rootpath, new_relpath)
        if os.path.lexists(new_path):
            messages.print_line("Skipped %s: %s is there already" % (relpath, new_relpath), "yellow")
            return False
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            self._copy_local_file_to_tree_with_path(os.path.join(self._rootpath, relpath), new_path)
        except OSError as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        # The tree may not have them, if it wasn't scanned (see dirdiff.py)
        if relpath in self:
            self.add_file_by_relpath(new_relpath)
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


def _rename(path, new_path):
    """Move path to new_path: a rename, or between filesystems (which a rename can't), a copy and a
    removal"""
    try:
        os.rename(path, new_path)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(path, new_path)
