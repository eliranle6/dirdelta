"""What a sync does to its replicas outside its screens: what one lacks of the other, reading
them anew, and whether files can go into them"""
import collections
import os

from googleapiclient.errors import HttpError

from dirdelta.drive import clouddirtree
from dirdelta.drive import drivecache
from dirdelta.trees import dirdiff
from dirdelta.trees import localdiskdirtree
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.util import dryrun
from dirdelta.util import text


# The relpaths of the files in a dir that another lacks (see find_missing()), and the lines of a
# warning if scanning couldn't read everything, so the diff may be wrong (or none)
Missing = collections.namedtuple('Missing', ['relpaths', 'warning'])


def find_missing(src, dst):
    """The files of src that dst lacks (Missing), each dir's together, sorted. Two local dirs are
    diffed with dirdiff, which scans them anew (so dirdelta needn't keep their trees, and its diff
    isn't from a stale scan); other trees are diffed as they are. Shows nothing, so it can run in
    the background. What dirdelta keeps in a replica (its paths.META_DIR) isn't one of its files."""
    missing = _find_missing(src, dst)
    return Missing([relpath for relpath in missing.relpaths if not paths.is_meta(relpath)], missing.warning)


def _find_missing(src, dst):
    if not (localdiskdirtree.is_local(src) and localdiskdirtree.is_local(dst)):
        missing = dst.get_unknown_entries_in_given_dirtree(src)
        # By path components, so a dir's files and subdirs stay together
        return Missing(sorted((entry.relpath for entry in missing.iter_files()),
                              key=lambda relpath: relpath.split('/')), [])
    relpaths, errors = dirdiff.files_not_in(src.fullpath(), dst.fullpath(), src.max_depth)
    return Missing(relpaths, localdiskdirtree.scan_warning(
        "%s or %s" % (src.fullpath(), dst.fullpath()), errors))


def scan_errors_warning(tree):
    """A warning's lines if scanning the (local) tree couldn't read everything; else none."""
    return localdiskdirtree.scan_warning(tree.fullpath(), getattr(tree, 'scan_errors', []))


def rescan_replica(replica):
    """Scan the local replica anew, on a screen, saying if it couldn't read everything. Returns whether
    it was; if not (stopped, or it isn't there), it's as it was."""
    name = replica.fullpath()
    is_done, error = False, None
    with messages.progress_screen("Rescanning %s" % (name,), dryrun.label(), wait=False):
        try:
            replica.rescan()
            is_done = True
        except OSError as failure:
            error = failure
    if error is not None:
        messages.show("Couldn't rescan it", [str(error)], dryrun.label(), 'red')
    warning = scan_errors_warning(replica) if is_done else []
    if warning:
        messages.show("Warning: couldn't read everything", warning, dryrun.label(), 'red')
    return is_done


def _read_anew(replica, relpath):
    """Read the replica anew (on Drive, its folder at relpath). Returns whether it was."""
    if isinstance(replica, clouddirtree.CloudDirTree):
        return refresh_replica(replica, relpath)
    return localdiskdirtree.is_local(replica) and rescan_replica(replica)


def refresh_replica(replica, relpath=''):
    """Read the cloud replica's folder at relpath (default: all of it) anew from Drive
    (CloudDirTree.refresh_from_drive()). Returns whether it was; if not, it's said why (on a screen),
    and the replica and the cache are as they were."""
    title = "Refresh %s from Google Drive" % (os.path.join(replica.displayname(), relpath).rstrip('/'),)
    try:
        replica.refresh_from_drive(relpath)
    except KeyboardInterrupt:
        messages.show(title, ["Stopped (Ctrl-C): the cloud files list cache is as it was."],
                      dryrun.label(), 'red')
    except (HttpError, OSError, drivecache.DriveCacheError) as error:
        messages.show(title, ["Couldn't refresh it: %s" % (error,)], dryrun.label(), 'red')
    else:
        return True
    return False


is_local = localdiskdirtree.is_local


def is_writable(replica):
    """Whether files can be copied into the replica, removed from it and moved in it: Drive, or a
    local dir with write permission (none on a read-only mount)"""
    return not is_local(replica) or os.access(replica.fullpath(), os.W_OK)


def can_copy(src, dst):
    """Whether src's files can be copied into dst: between a local dir and anything (not within
    Drive), into a writable one"""
    return is_writable(dst) and (is_local(src) or is_local(dst))


_files = text.files


def _exists(replica, relpath):
    """Whether the replica has a file or dir at relpath"""
    return os.path.lexists(os.path.join(replica.fullpath(), relpath)) if is_local(replica) else replica.exists(relpath)
