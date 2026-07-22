import os
import sys

import clouddirtree
import clouddirtreefactory
import cursesswitch
import localdiskdirtree


def create_dirtree_from_arg(rootpath):
    if __is_cloud_path(rootpath):
        # Create a cloud dir tree
        dirtree = clouddirtreefactory.factory_interactive(rootpath)
    else:
        # Assume dirpath is in a local filesystem
        __validate_replica(rootpath)
        dirpath = os.path.realpath(rootpath)
        dirtree = localdiskdirtree.factory(rootpath)

    return dirtree


def __is_cloud_path(path):
    return _first_path_comp(path) == 'cloud'


def _first_path_comp(path):
    components = clouddirtree.CloudDirTree.path_components(path)
    return components[0]


def __validate_replica(replica_path):
    if replica_path is not None and not os.path.isdir(replica_path):
        cursesswitch.print_string("{} is not a directory".format(replica_path))
        sys.exit(1)
