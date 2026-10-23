import json
import os

import dirtree


FILE_LIST_CACHE = os.path.expanduser('~/.cache/dirman/files.txt')


class CloudDirTree(dirtree.DirTree):
    """A dir tree representing a directory on the cloud.

    Note that this class requires a factory to make sure that the cache file containing the list of files
    in the cloud exists and is updated.
    """
    def __init__(self, rootpath):
        rootpath = self._path_in_cloud(rootpath)
        id_child_map, id_md_map, root_id = self._parsefile(FILE_LIST_CACHE)
        super(CloudDirTree, self).__init__(rootpath=rootpath)
        self._dirdict_to_dirtree(id_child_map, id_md_map, root_id, rootpath)

    def _parseline(self, line, id_child_map, id_md_map):
        # Skip non-dict lines
        if not line.startswith('{'):
            return

        # Parse dict
        md = json.loads(line)

        # Determine root
        if 'parents' not in md:
            parent = 'shared'
        else:
            parent = md['parents'][0]

        # Populate metadata map
        id = md['id']
        id_md_map[id] = md

        # Populate children map
        # Initialize children list for parent of current node
        if parent not in id_child_map:
            id_child_map[parent] = []
        id_child_map[parent].append(id)
        # Initialize children list for current node.
        # Do this only if it's not already in id_child_map as parent, because if one of its children has appeared
        # before, then it would already be in the map as a parent (so we don't want to delete it).
        if id not in id_child_map:
            id_child_map[id] = []


    def _parsefile(self, filename):
        """Scan drive file list and produce an id->child and id->metadata map.

        This is required as a preceding step before creating a DirTree object, because the second step
        (node creation) has to be done in such an order so that the parent was inserted before the child.
        """
        id_child_map = {}
        id_md_map = {}

        with open(filename) as f:
            for line in f:
                self._parseline(line, id_child_map, id_md_map)

        # Find root
        if 'shared' in id_child_map:
            del id_child_map['shared']
        no_md = set(id_child_map).difference(id_md_map)
        assert len(no_md) == 1
        root = no_md.pop()

        return id_child_map, id_md_map, root

    def _dirdict_to_dirtree(self, id_child_map, id_md_map, root_cloud_id, inner_rootpath):
        """Create child nodes from the given id->child and id->metadata maps."""
        # Create stack with root node
        dfs_stack = [(root_cloud_id, None)]

        while dfs_stack:
            # Pop
            node_cloud_id, parent_path = dfs_stack.pop()

            # Visit
            if node_cloud_id == root_cloud_id:
                filename = '/'
                node_path = '/'
            else:
                md = id_md_map[node_cloud_id]
                filename = md.get('name', '')
                node_path = os.path.join(parent_path, filename)

                # Create node, only if under the requested inner root
                under_inner_root = (parent_path + '/').startswith(inner_rootpath.rstrip('/') + '/')
                if under_inner_root:
                    # Generate relative path
                    node_rel_path = '/' + os.path.relpath(node_path, inner_rootpath)
                    # Change node ID if it already exists (two files with the same path is possible in cloud)
                    if node_rel_path in self.nodes:
                        node_rel_path += f'___DUP__{node_cloud_id}'

                    # Generate parent relative path
                    if parent_path == inner_rootpath:
                        parent_rel_path = '/'
                    else:
                        parent_rel_path = os.path.relpath(parent_path, inner_rootpath)

                    node_rel_path = node_rel_path.lstrip('/')

                    is_dir = md['mimeType'] == 'application/vnd.google-apps.folder'
                    if is_dir:
                        self.create_dir_node_from_relpath_if_not_exists(node_rel_path)
                    else:
                        self.add_file_by_relpath(node_rel_path)

            # Add children to stack
            for child_cloud_id in id_child_map[node_cloud_id]:
                dfs_stack.append((child_cloud_id, node_path))

    @staticmethod
    def _path_in_cloud(path):
        # Assume first component is 'cloud'
        components = CloudDirTree.path_components(path)
        return '/' + '/'.join(components[1:])

    @staticmethod
    def path_components(path):
        return [p for p in path.split('/') if p]
