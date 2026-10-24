from dirdelta import dirtree
from dirdelta import drivecache
from dirdelta import paths


class CloudDirTree(dirtree.DirTree):
    """A dir tree representing a directory on the cloud.

    Note that this class requires a factory to make sure that the cache file containing the list of files
    in the cloud exists and is updated.
    """
    def __init__(self, rootpath):
        rootpath = paths.path_in_cloud(rootpath)
        super(CloudDirTree, self).__init__(rootpath=rootpath)
        for relpath, cloud_id, is_dir in drivecache.entries(rootpath):
            # Change node ID if it already exists (two files with the same path is possible in cloud)
            if relpath in self:
                relpath += f'___DUP__{cloud_id}'
            if is_dir:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
            else:
                self.add_file_by_relpath(relpath)
