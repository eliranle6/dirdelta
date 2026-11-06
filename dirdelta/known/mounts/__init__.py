"""The volumes that local replicas are on, kept in MOUNTS_FILE (JSON) so that one that isn't mounted
now (a disk's partition mounted by hand, an external disk) is found before it's scanned, and can be
mounted again where it was.

An unmounted mount point is still a dir, an empty one on the root filesystem: scanning it would say
that every file is missing, and a live Copy would fill the root filesystem rather than the volume.
So before a replica is used, the recorded mount it's under is checked, and if it isn't mounted the
user is asked whether to mount it (by its UUID, the device's name may differ next time), at the same
mount point, so the replica's path still holds. Mounting changes the system, not files, so it's
asked even in a dry run, and never done without asking.

Its parts are in the modules here; the names the rest of dirdelta uses are here too (but
MOUNTS_FILE and BY_UUID_DIR, which are names': set them there)."""
from dirdelta.known.mounts.current import current_mount, remember, unmounted  # noqa: F401
from dirdelta.known.mounts.file import load, save  # noqa: F401
from dirdelta.known.mounts.mounting import ensure_mounted, is_connected, mount_command  # noqa: F401
from dirdelta.known.mounts.names import (BACK, HIBERNATION_FILE, MOUNT, TRY_AGAIN, Mount,  # noqa: F401
                                         MountsError)
from dirdelta.known.mounts.read_only import read_only_lines_of, read_only_reason  # noqa: F401
