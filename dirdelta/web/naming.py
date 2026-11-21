"""What the web version calls a replica (name()): its one name, as every screen calls it (its label, else
its disk: replicanames.name()); and where it is (place()), said apart: 'Drive', 'disk win', 'this computer'"""
import os
import threading
import time

from dirdelta.known import mounts
from dirdelta.known import replicanames
from dirdelta.trees import paths

# How long where a local path is (findmnt's) is taken as known, in seconds
PLACE_FOR = 30

# {path: (when, its place)}
_places = {}
_lock = threading.Lock()


def own_name(path):
    """The replica's one name, as every screen calls it (replicanames.name(): its label, else its disk)"""
    return replicanames.name(path)


def place(path):
    """Where the replica at path is: 'Drive', 'this computer' (the system's disk), or 'disk NAME' (the
    mount point's name, e.g. 'disk win')"""
    if paths.is_cloud_path(path):
        return 'Drive'
    now = time.monotonic()
    with _lock:
        found = _places.get(path)
    if found is not None and now - found[0] < PLACE_FOR:
        return found[1]
    mount = mounts.current_mount(path)
    if mount is None or mount.target in ('/', '/home'):
        found = 'this computer'
    else:
        found = 'disk ' + (mount.label or os.path.basename(mount.target.rstrip('/')) or mount.target) if mount.target else 'disk'
    with _lock:
        _places[path] = (now, found)
    return found


def name(path):
    """The replica's name (own_name(): where it is is shown apart, see place())"""
    return own_name(path)
