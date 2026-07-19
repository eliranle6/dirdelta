import os
import sys
import treelib


def factory_from_list_of_file_entries(files, filesystem_dirpath):
    filesystem_dirpath = os.path.realpath(filesystem_dirpath)
    filesystem_basename = os.path.basename(filesystem_dirpath)
    dirtree = DirTree(filesystem_dirpath)
    for file_entry in files:
        file_first_component, inner_path = file_entry.fullpath.split(os.path.sep, 2)[1:]
        if file_first_component != filesystem_basename:
            raise ValueError("File's first path component must match that of filesystem path",
                                file_entry, filesystem_dirpath, file_first_component, filesystem_basename)
        inner_dirpath = os.path.dirname(inner_path)
        parent_dir_node = dirtree.get_dir_node(inner_dirpath)
        dirtree.create_node(identifier=file_entry.fullpath,
                                tag=file_entry.name,
                                data=file_entry,
                                parent=parent_dir_node.identifier)
    return dirtree


class DirEntry(object):
    """
    A DirTree node that Represents a filesystem directory.

    name: The dir's basename
    path: The dir's parent's relative path from the tree's root dir
    filesystem_dirpath: The tree's root absolute parent path

    Example:
    The dirtree's root is in /home/users/blah
    An entry is located in /home/users/blah/subdir1/subdir2
    Hence,
    name: subdir2
    relpath: /blah/subdir2
    fullpath: /home/users/blah/subdir2
    """

    def __init__(self, name, parent_relpath, parent_fullpath=None):
        if parent_fullpath is None:
            parent_fullpath = parent_relpath
        self.name = name
        self.relpath = os.path.join(parent_relpath, name)
        if name == os.path.sep:
            # os.path.join(parent_fullpath, name) would normally discard
            # parent_fullpath here, since a second argument of '/' is itself
            # absolute - but for the tree's root entry (the only entry ever
            # constructed with name == '/'), parent_fullpath already IS the
            # entry's own fullpath, so it should pass through unchanged.
            self.fullpath = parent_fullpath
        else:
            self.fullpath = os.path.join(parent_fullpath, name)

    def __repr__(self):
        return self.fullpath

    def full_filesystem_path(self):
        return self.fullpath


class FileEntry(object):
    def __init__(self, name, parent_dir_entry):
        self.name = name
        self.relpath = os.path.join(parent_dir_entry.relpath, self.name)
        self.fullpath = os.path.join(parent_dir_entry.fullpath, self.name)

    def __repr__(self):
        return self.relpath

    def full_filesystem_path(self):
        return self.fullpath


MUSIC_FILE_EXTENTIONS = ["mp3", "mp4", "wav", "ogg", "wmv", "wma"]


class DirTree(treelib.Tree):
    """
    The tree will be created as follows:
        Root node:
            id='/'
            tag=root path (for instance /home/blah/myfiles/)
            data=Root node entry

    The full filesystem path can be obtained from the data (node.data.full_filesystem_path())
    """
    def __init__(self, rootpath, silent=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._silent = silent

        if len(rootpath) > 1 and rootpath.endswith('/'):
            rootpath = os.path.basename(rootpath)
        self._rootpath = rootpath
        root = DirEntry(name='/', parent_relpath='/', parent_fullpath=self._rootpath)
        self._create_node_orig = self.create_node
        self._root = self.create_node(identifier='/', tag=root.name, data=root)
        self.create_node = self._create_node_override_method

    def create_dir_node_from_fullpath_if_not_exists(self, fullpath):
        # Convert to relative path
        relpath = os.path.relpath(fullpath, self.fullpath())

        return self.create_dir_node_from_relpath_if_not_exists(relpath)

    def create_dir_node_from_relpath_if_not_exists(self, relpath):
        # Make sure all subdires have nodes
        parts = relpath.split(os.path.sep)
        cur_subdir = self._root
        for subdir_name in parts:
            cur_subdir = self._set_default_subdir(parent=cur_subdir, name=subdir_name)

        return cur_subdir

    def add_file_by_fullpath(self, fullpath):
        relpath = os.path.relpath(fullpath, self.fullpath())
        self.add_file_by_relpath(relpath)

    def add_file_by_relpath(self, relpath):
        dirpath = os.path.dirname(relpath)
        parent_dir_node = self.create_dir_node_from_relpath_if_not_exists(dirpath)
        filename = os.path.basename(relpath)
        _file = FileEntry(filename, parent_dir_entry=parent_dir_node.data)
        file_entry = self._create_node_orig(
            identifier=_file.relpath,
            tag=_file.name,
            data=_file,
            parent=parent_dir_node)
        return file_entry.data

    def iter_files(self):
        for node in self.nodes.values():
            if isinstance(node.data, FileEntry):
                yield node.data

    def does_dir_contain_any_files(self):
        return any(isinstance(entry, FileEntry) for entry in self.iter_files())

    def get_unknown_entries_in_given_dirtree(self, other):
        unknown_files_dirtree = DirTree(other._rootpath)

        unknown_files = []
        for file_entry in other.iter_files():
            if file_entry.relpath not in self.nodes:
                unknown_files.append(file_entry)

        for _file in unknown_files:
            unknown_files_dirtree.add_file_by_relpath(_file.relpath)
        return unknown_files_dirtree

    def fullpath(self):
        return self._rootpath

    @staticmethod
    def _remove_prefix_from_path(name, _path):
        prefix = os.path.sep + name + os.path.sep
        assert _path.startswith(prefix)
        relative_path = _path[len(prefix):]
        return relative_path

    def _set_default_subdir(self, parent, name):
        relpath = os.path.join(parent.data.relpath, name)
        fullpath = os.path.join(parent.data.fullpath, name)
        node = self.get_node(relpath)
        if node is None:
            subdir_entry = DirEntry(name, parent_relpath=parent.data.relpath,
                                    parent_fullpath=parent.data.fullpath)
            node = self._create_node_orig(
                identifier=relpath,
                tag=name,
                data=subdir_entry,
                parent=parent.identifier)
        return node

    def _create_node_override_method(self, *_, **__):
        raise NotImplementedError('Please use create_dir_node_from_fullpath_if_not_exists, '
            'add_file_by_relpath, or add_file_by_fullpath')


if __name__ == '__main__':
#    #import sys
#    t = LocalDiskFSTree.factory(sys.argv[1], silent=True)
     t.show()
