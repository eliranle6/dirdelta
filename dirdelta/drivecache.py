"""The cache of Google Drive's file list (FILE_LIST_CACHE): one JSON line per file or folder, with
its id, name, parents and mimeType, as the Drive API lists them (clouddirtreefactory writes it).
entries() reads it into the paths of what's under a folder."""
import json
import os

FILE_LIST_CACHE = os.path.expanduser('~/.cache/dirman/files.txt')

FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'


def entries(inner_rootpath):
    """Yield (relpath, cloud_id, is_dir) for each file and folder under inner_rootpath (a path in the
    cloud, like /mein), each folder before what's in it. relpath is relative to inner_rootpath; two
    entries can have the same one, since Drive allows same-named files."""
    id_child_map, id_md_map, root_cloud_id = _parsefile(FILE_LIST_CACHE)
    # Create stack with root node
    dfs_stack = [(root_cloud_id, None)]

    while dfs_stack:
        # Pop
        node_cloud_id, parent_path = dfs_stack.pop()

        # Visit
        if node_cloud_id == root_cloud_id:
            node_path = '/'
        else:
            md = id_md_map[node_cloud_id]
            node_path = os.path.join(parent_path, md.get('name', ''))

            # Only what's under the requested inner root
            under_inner_root = (parent_path + '/').startswith(inner_rootpath.rstrip('/') + '/')
            if under_inner_root:
                yield (os.path.relpath(node_path, inner_rootpath), node_cloud_id,
                       md['mimeType'] == FOLDER_MIME_TYPE)

        # Add children to stack
        for child_cloud_id in id_child_map[node_cloud_id]:
            dfs_stack.append((child_cloud_id, node_path))


def _parseline(line, id_child_map, id_md_map):
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


def _parsefile(filename):
    """Scan drive file list and produce an id->child and id->metadata map.

    This is required as a preceding step before creating a tree, because the second step
    (node creation) has to be done in such an order so that the parent was inserted before the child.
    """
    id_child_map = {}
    id_md_map = {}

    with open(filename) as f:
        for line in f:
            _parseline(line, id_child_map, id_md_map)

    # Find root
    if 'shared' in id_child_map:
        del id_child_map['shared']
    no_md = set(id_child_map).difference(id_md_map)
    assert len(no_md) == 1
    root = no_md.pop()

    return id_child_map, id_md_map, root
