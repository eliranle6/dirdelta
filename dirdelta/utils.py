import os
import sys

import clouddirtree
import clouddirtreefactory
import cursesswitch
import localdiskdirtree


def create_dirtree_from_arg(rootpath, max_depth=None):
    if __is_cloud_path(rootpath):
        # Create a cloud dir tree
        dirtree = clouddirtreefactory.factory_interactive(rootpath)
    else:
        # Assume dirpath is in a local filesystem
        __validate_replica(rootpath)
        dirtree = localdiskdirtree.factory(rootpath, max_depth=max_depth)

    return dirtree


def __is_cloud_path(path):
    return clouddirtree.CloudDirTree.path_components(path)[:1] == ['cloud']


def __validate_replica(replica_path):
    if replica_path is not None and not os.path.isdir(replica_path):
        cursesswitch.print_string("{} is not a directory".format(replica_path))
        sys.exit(1)
