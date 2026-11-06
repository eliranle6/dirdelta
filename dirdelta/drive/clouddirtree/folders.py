"""Making the folders that files go into, a level of them in a batch"""
import collections
import os

from googleapiclient.errors import HttpError

from dirdelta.drive import driveapi
from dirdelta.drive import drivecache
from dirdelta.drive.clouddirtree.constants import MAX_BATCH_SIZE, MAX_GENERATED_IDS, NUM_RETRIES
from dirdelta.ui import messages


class Folders(object):
    """Making folders (CloudDirTree's)"""

    def _make_folders(self, dir_relpaths):
        """Make the folders at dir_relpaths, and the ones they're in, that Drive lacks: their ids
        asked for first, so each level's are made in batch requests (up to MAX_BATCH_SIZE folders
        each), knowing the ids of their parents (made by the level before). One that can't be made
        is left to _folder_id(), when its files are uploaded."""
        needed = set()
        for relpath in dir_relpaths:
            while relpath and relpath not in self._cloud_ids and relpath not in needed:
                needed.add(relpath)
                relpath = os.path.dirname(relpath)
        if not needed:
            return
        messages.print_line("Making %d folders in %s" % (len(needed), self.displayname()))
        levels = collections.defaultdict(list)
        for relpath in sorted(needed):
            levels[relpath.count('/')].append(relpath)
        try:
            ids = dict(zip(sorted(needed), self._generate_ids(len(needed))))
            for depth in sorted(levels):
                relpaths = levels[depth]
                for start in range(0, len(relpaths), MAX_BATCH_SIZE):
                    self._make_folders_batch(relpaths[start:start + MAX_BATCH_SIZE], ids)
        except HttpError as error:
            messages.print_line("Couldn't make the folders (%s): making each with its files" % (error,),
                                "red")

    def _generate_ids(self, count):
        """count ids for new files or folders, from Drive"""
        ids = []
        while len(ids) < count:
            request = driveapi.service().files().generateIds(
                count=min(MAX_GENERATED_IDS, count - len(ids)), space='drive')
            ids += request.execute(num_retries=NUM_RETRIES)['ids']
        return ids

    def _make_folders_batch(self, relpaths, ids):
        """Make the folders at relpaths (whose parents are made), with ids, in one batch request"""
        service = driveapi.service()
        bodies = []

        def made(request_id, response, error):
            relpath, body = bodies[int(request_id)]
            if error is not None:
                messages.print_line("Couldn't make folder %s (%s): trying again with its files" %
                                    (relpath, error), "red")
                return
            self._cache_add(dict(body, **response))
            self.create_dir_node_from_relpath_if_not_exists(relpath)
            self._cloud_ids[relpath] = response['id']

        batch = service.new_batch_http_request(callback=made)
        for relpath in relpaths:
            parent_id = self._cloud_ids.get(os.path.dirname(relpath))
            # Its parent couldn't be made
            if parent_id is None:
                continue
            body = {'id': ids[relpath], 'name': os.path.basename(relpath),
                    'mimeType': drivecache.FOLDER_MIME_TYPE, 'parents': [parent_id]}
            # By index: a path may have characters a request id can't
            batch.add(service.files().create(body=body, fields=drivecache.FILE_FIELDS),
                      request_id=str(len(bodies)))
            bodies.append((relpath, body))
        if bodies:
            batch.execute()

    def _folder_id(self, relpath):
        """The Drive id of the folder at relpath, making it (and the folders it's in) if needed"""
        if relpath not in self._cloud_ids:
            parent_id = self._folder_id(os.path.dirname(relpath))
            body = {'name': os.path.basename(relpath), 'mimeType': drivecache.FOLDER_MIME_TYPE,
                    'parents': [parent_id]}
            created = driveapi.service().files().create(
                body=body, fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
            self._cache_add(dict(body, **created), relpath)
            self.create_dir_node_from_relpath_if_not_exists(relpath)
            self._cloud_ids[relpath] = created['id']
        return self._cloud_ids[relpath]
