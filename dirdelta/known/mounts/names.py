"""Where the mounts are kept, what's looked for, the mount question's options, and a Mount"""
import collections
import os


MOUNTS_FILE = os.path.expanduser('~/.config/dirdelta/mounts.json')
# Where a connected disk's partitions are, by their filesystems' UUIDs
BY_UUID_DIR = '/dev/disk/by-uuid'
# What ntfs-3g says when Windows hibernated, or shut down with Fast Startup on: it won't mount it
# read-write
UNCLEAN_NTFS_ERRORS = ('unclean file system', 'hibernated', 'windows cache')
# How a Windows volume says it has a saved session: its hibernation file, starting so
HIBERNATION_FILE = 'hiberfil.sys'
HIBERNATED_MARK = b'HIBR'

MOUNT = 'Mount it'
TRY_AGAIN = "Try again (once it's connected)"
BACK = 'Back'

# A volume as it was mounted: its mount point, device (as it was named then), filesystem type,
# options (the mount's, e.g. 'rw,relatime', and the filesystem's, e.g. 'uid=1000'), UUID and label
Mount = collections.namedtuple('Mount', ['target', 'source', 'fstype', 'vfs_options', 'fs_options',
                                         'uuid', 'label'])


class MountsError(Exception):
    pass
