"""The folders all of whose files are removed, trashed as one"""
from googleapiclient.errors import HttpError

from dirdelta.drive.clouddirtree.constants import MAX_FOLDERS_PER_QUERY
from dirdelta.drive.clouddirtree.refresh import _list
from dirdelta.trees import entries
from dirdelta.ui import messages


class WholeFolders(object):
    """Whole folders (CloudDirTree's)"""

    def _whole_folders(self, picked, holding_more=frozenset()):
        """The topmost folders (not the root) with a picked file (of picked, relpaths) in them, all
        of whose files are picked: nothing in them would be left. Folders of holding_more (relpaths),
        and those they're in, never are."""
        # Each folder's (whether it has a picked file, whether all of its files are)
        found = {}

        def walk(relpath):
            has_picked, is_whole = False, relpath not in holding_more
            for node in self.children(relpath):
                if isinstance(node.data, entries.FileEntry):
                    if node.identifier in picked:
                        has_picked = True
                    else:
                        is_whole = False
                else:
                    child_has_picked, child_is_whole = walk(node.identifier)
                    has_picked = has_picked or child_has_picked
                    is_whole = is_whole and child_is_whole
            found[relpath] = (has_picked, is_whole)
            return has_picked, is_whole

        folders = []

        def collect(relpath):
            for node in self.children(relpath):
                if isinstance(node.data, entries.DirEntry):
                    has_picked, is_whole = found[node.identifier]
                    if has_picked and is_whole:
                        folders.append(node.identifier)
                    elif has_picked:
                        collect(node.identifier)

        walk(self.root)
        collect(self.root)
        return folders

    def _folders_holding_more(self, folders):
        """Of folders (relpaths) and the folders in them, those that Drive has something in that
        the tree doesn't (a relpath set), asking Drive what's in each (MAX_FOLDERS_PER_QUERY of them
        a request); None if Drive couldn't be asked (said why)"""
        folder_ids = {}
        # A folder whose id the tree lacks can't be asked about
        holding_more = set()
        for folder in folders:
            for node in self._tree.subtree(folder).all_nodes_itr():
                if isinstance(node.data, entries.DirEntry):
                    if node.identifier in self._cloud_ids:
                        folder_ids[self._cloud_ids[node.identifier]] = node.identifier
                    else:
                        holding_more.add(node.identifier)
        known_ids = set(self._cloud_ids.values())
        messages.print_line("Checking %d folders with Drive before trashing them..." % (len(folder_ids),))
        ids = sorted(folder_ids)
        try:
            for start in range(0, len(ids), MAX_FOLDERS_PER_QUERY):
                query = "(%s) and trashed = false" % (' or '.join(
                    "'%s' in parents" % (cloud_id,) for cloud_id in ids[start:start + MAX_FOLDERS_PER_QUERY]))
                for md in _list(query):
                    if md['id'] not in known_ids:
                        holding_more.update(folder_ids[parent] for parent in md.get('parents', [])
                                            if parent in folder_ids)
        except HttpError as error:
            messages.print_line("Couldn't check the folders with Drive (%s): removing their files "
                                "one by one" % (error,), "yellow")
            return None
        return holding_more
