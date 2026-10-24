from dirdelta import dirtree
from dirdelta import drivecache
from dirdelta import paths


def factory(rootpath):
    """The tree of the cloud path rootpath (e.g. cloud/mein), from the Drive file list cache, which
    must exist (clouddirtreefactory makes sure it does)."""
    tree = CloudDirTree(rootpath)
    tree.update_from_cache()
    return tree


class CloudDirTree(dirtree.DirTree):
    """A dir tree representing a directory on the cloud (Google Drive)."""
    def __init__(self, rootpath):
        super(CloudDirTree, self).__init__(rootpath=paths.path_in_cloud(rootpath))

    def update_from_cache(self):
        """Add the files and folders in the Drive file list cache (drivecache) under the tree's root"""
        for relpath, cloud_id, is_dir in drivecache.entries(self.fullpath()):
            # Change node ID if it already exists (two files with the same path is possible in cloud)
            if relpath in self:
                relpath += f'___DUP__{cloud_id}'
            if is_dir:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
            else:
                self.add_file_by_relpath(relpath)
