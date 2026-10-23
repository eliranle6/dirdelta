import os
import sys

from dirdelta import clouddirtree
from dirdelta import clouddirtreefactory
import cursesswitch
from dirdelta import localdiskdirtree


def create_dirtree_from_arg(rootpath, max_depth=None):
    if is_cloud_path(rootpath):
        # Create a cloud dir tree
        dirtree = clouddirtreefactory.factory_interactive(rootpath)
    else:
        # Assume dirpath is in a local filesystem
        validate_dir(rootpath)
        dirtree = localdiskdirtree.factory(rootpath, max_depth=max_depth)

    return dirtree


def is_cloud_path(path):
    return clouddirtree.CloudDirTree.path_components(path)[:1] == ['cloud']


def validate_dir(replica_path):
    """Exit with a message unless replica_path is a dir (or None)."""
    if replica_path is not None and not os.path.isdir(replica_path):
        cursesswitch.print_line("{} is not a directory".format(replica_path))
        sys.exit(1)
