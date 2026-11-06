"""One listing of a local dir, for all that lists one: by one find (faster than os.walk, see
docs), its files and dirs (other types, e.g. symlinks, aren't in it), each with its size and
modification time."""
import os
import subprocess
import tempfile

# How much of find's output is read at a time, at most
READ_SIZE = 1 << 16

DIR, FILE = 'd', 'f'


class Scan(object):
    """What scan() found: entries, {relpath: (kind (DIR or FILE), size, mtime_ns)}, in find's order,
    and errors, find's messages about what it couldn't read (so entries may lack it)"""
    def __init__(self, entries, errors):
        self.entries = entries
        self.errors = errors

    def files(self):
        """{relpath: (size, mtime_ns)} of the files"""
        return {relpath: (size, mtime_ns) for relpath, (kind, size, mtime_ns) in self.entries.items() if kind == FILE}


# How deep a replica is listed, unless it's said otherwise (main's --max-depth)
DEFAULT_MAX_DEPTH = 20


def scan(root, max_depth=None, progress=None):
    """A Scan of what's under the dir at root (down to max_depth levels). progress, if given, is
    called as it goes with how many it found so far, and may raise, to stop it (find is stopped too).
    Raises OSError if find can't be run."""
    command = ['find', root, '-mindepth', '1']
    if max_depth is not None:
        command += ['-maxdepth', str(max_depth)]
    command += ['(', '-type', 'd', '-o', '-type', 'f', ')', '-printf', '%y %s %T@ %P\\0']
    entries = {}
    # The start of an entry whose end hasn't been read yet
    pending = b''
    # Its errors in a file, not a pipe: reading two pipes one after the other could block find on a full one
    with tempfile.TemporaryFile() as errors_file:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors_file)
        try:
            for chunk in iter(lambda: process.stdout.read1(READ_SIZE), b''):
                items = (pending + chunk).split(b'\0')
                pending = items.pop()
                for item in items:
                    kind, size, mtime, relpath = item.split(b' ', 3)
                    # Names needn't be valid UTF-8: decoded like Python decodes paths
                    entries[os.fsdecode(relpath)] = (kind.decode('ascii'), int(size), nanoseconds(mtime.decode('ascii')))
                if progress is not None:
                    progress(len(entries))
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.wait()
        errors_file.seek(0)
        errors = errors_file.read().decode('utf-8', 'surrogateescape').splitlines()
    return Scan(entries, errors)


def nanoseconds(timestamp):
    """find's %T@ (seconds, e.g. '1698765432.1234567890') in nanoseconds, as os.stat()'s st_mtime_ns"""
    seconds, _, fraction = timestamp.partition('.')
    if seconds.startswith('-'):
        return int(round(float(timestamp) * 10 ** 9))
    return int(seconds) * 10 ** 9 + int((fraction + '000000000')[:9])
