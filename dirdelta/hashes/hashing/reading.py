"""Reading a file to hash it: at the lowest priority, without filling the page cache"""
import ctypes
import hashlib
import os
import platform
import threading

from dirdelta.hashes.hashing.states import ALGORITHM, READ_SIZE
from dirdelta.trees import localscan


class Paused(Exception):
    pass


def hash_file(path, is_paused):
    """(The file's hash, its [size, mtime_ns] when it was read), or (None, None) if it can't be read
    or changed while it was. Raises _Paused once is_paused() says so."""
    digest = hashlib.new(ALGORITHM)
    try:
        with open(path, 'rb') as f:
            before = os.fstat(f.fileno())
            for chunk in iter(lambda: f.read(READ_SIZE), b''):
                if is_paused():
                    raise Paused()
                digest.update(chunk)
            _drop_from_page_cache(f.fileno())
        after = os.stat(path)
    except OSError:
        return None, None
    stamp = [before.st_size, before.st_mtime_ns]
    if [after.st_size, after.st_mtime_ns] != stamp:
        return None, None
    return digest.hexdigest(), stamp


def _drop_from_page_cache(fd):
    """Read once, the file needn't push what the user works with out of memory"""
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    except (AttributeError, OSError):
        pass


# ioprio_set's syscall numbers, by machine, and its idle class (only when the disk is otherwise idle)
_IOPRIO_SET = {'x86_64': 251, 'aarch64': 30}
_IOPRIO_WHO_PROCESS = 1
_IOPRIO_CLASS_IDLE = 3
_IOPRIO_CLASS_SHIFT = 13


def lower_priority():
    """The calling thread's CPU priority the lowest (nice 19), and its I/O priority idle: hashing
    gives way to anything else (on Linux; elsewhere it's as it is)"""
    try:
        thread_id = threading.get_native_id()
        os.setpriority(os.PRIO_PROCESS, thread_id, 19)
    except (AttributeError, OSError):
        return
    syscall = _IOPRIO_SET.get(platform.machine())
    if syscall is None:
        return
    try:
        ctypes.CDLL(None, use_errno=True).syscall(syscall, _IOPRIO_WHO_PROCESS, thread_id,
                                                   _IOPRIO_CLASS_IDLE << _IOPRIO_CLASS_SHIFT)
    except (OSError, AttributeError):
        pass


def list_files(root, max_depth=None):
    """{relpath: (size, mtime_ns)} of the files under root (down to max_depth levels). Raises OSError
    if they can't be listed."""
    return localscan.scan(root, max_depth).files()
