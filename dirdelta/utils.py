import os
import sys

from dirdelta import clouddirtreefactory
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import paths


def create_dirtree_from_arg(rootpath, max_depth=None):
    """The tree of the replica at rootpath: a local dir's, scanned, or a Drive folder's, from the
    cache (refreshed if the user wants); None if the user chose nothing, asked whether to refresh"""
    if paths.is_cloud_path(rootpath):
        # Create a cloud dir tree
        dirtree = clouddirtreefactory.factory_interactive(rootpath)
    else:
        # Assume dirpath is in a local filesystem
        validate_dir(rootpath)
        dirtree = localdiskdirtree.factory(rootpath, max_depth=max_depth)

    return dirtree


def validate_dir(replica_path):
    """Exit with a message unless replica_path is a dir (or None)."""
    if replica_path is not None and not os.path.isdir(replica_path):
        messages.print_line("{} is not a directory".format(replica_path))
        sys.exit(1)
