import collections
import concurrent.futures
import os
import posixpath

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from dirdelta import dirtree
from dirdelta import driveapi
from dirdelta import drivecache
from dirdelta import dryrun
from dirdelta import entries
from dirdelta import messages
from dirdelta import paths

# How many files are uploaded at once. A few: Drive limits how fast a user makes files (about 2-3 a
# second), so more would only meet its rate limit errors.
UPLOAD_THREADS = 4
# Smaller files are uploaded in one request; bigger ones as resumable uploads (a request to start,
# then the data in chunks), worth it only where a cut-off upload has much to lose
RESUMABLE_MIN_SIZE = 5 * 1024 * 1024
# How many times the client retries a request that failed on a rate limit or a server error, waiting
# longer each time (exponential backoff)
NUM_RETRIES = 5
# The most requests in a batch request, and ids that generateIds gives at once (the API's limits)
MAX_BATCH_SIZE = 100
MAX_GENERATED_IDS = 1000
# How many folders one files().list asks what's in ("'A' in parents or 'B' in parents ..."), short
# of a query Drive finds too long or complex
MAX_FOLDERS_PER_QUERY = 30
# How many of the folders or files a confirmation's note lists
MAX_LISTED = 5
# What's added to a file's relpath (with its id after it) when the tree already has one there
DUP_SUFFIX = '___DUP__'


def factory(rootpath):
    """The tree of the cloud path rootpath (e.g. cloud/mein), from the Drive file list cache, which
    must exist (clouddirtreefactory makes sure it does)."""
    tree = CloudDirTree(rootpath)
    tree.update_from_cache()
    return tree


class CloudDirTree(dirtree.DirTree):
    """A dir tree representing a directory on the cloud (Google Drive). Files are copied into it by
    uploading them, out of it by downloading them, and removed from it to Drive's trash: a folder all
    of whose files are removed, as one.

    Google's own files (Docs, Sheets, ...) are in it too, by their names and an extension (see
    drivecache.path_name()). They can be removed, but not copied out: they're not files to
    download."""
    REMOVED_TO = " (to Drive's trash)"

    def __init__(self, rootpath):
        super(CloudDirTree, self).__init__(rootpath=paths.path_in_cloud(rootpath))
        # Each file's and folder's Drive id, by its relpath (the root's is '')
        self._cloud_ids = {}
        # The relpaths of the Google files
        self._google_files = set()
        # Each file's size, by its relpath (none for a Google file)
        self._sizes = {}

    def displayname(self):
        """The cloud path, as given (cloud/mein), rather than the path in Drive (/mein), which
        reads like a local dir"""
        return paths.join_cloud(self.fullpath())

    def update_from_cache(self, found=None):
        """Add the files and folders in the Drive file list cache (drivecache) under the tree's root
        (or found: drivecache.entries() of it, already read)"""
        if found is None:
            found = drivecache.entries(self.fullpath())
        for relpath, cloud_id, is_dir, is_google_file, size in found:
            if relpath == '':
                self._cloud_ids[relpath] = cloud_id
                continue
            # Change node ID if it already exists (two files with the same path is possible in cloud)
            if relpath in self:
                relpath += DUP_SUFFIX + cloud_id
            if is_dir:
                self.create_dir_node_from_relpath_if_not_exists(relpath)
            else:
                self.add_file_by_relpath(relpath)
                if is_google_file:
                    self._google_files.add(relpath)
                if size is not None:
                    self._sizes[relpath] = size
            self._cloud_ids[relpath] = cloud_id

    def refresh_from_drive(self, relpath=''):
        """Read the folder at relpath (default: the tree's root) anew from Drive, into the cache
        (refresh_cache()), and rebuild the tree from it. A relpath the tree has no folder at (e.g.
        a dir only the other replica has) refreshes the closest folder above it that it has.
        Returns the relpath refreshed. Raises as refresh_cache() does, or DriveCacheError if what's
        there can't be a tree; either way (and on Ctrl-C), the tree is as it was."""
        while relpath and not isinstance(getattr(self.get_node(relpath), 'data', None), entries.DirEntry):
            relpath = os.path.dirname(relpath)
        refresh_cache(posixpath.join(self.fullpath(), relpath))
        # Read before the tree is emptied, so it's kept if they can't be a tree
        found = list(drivecache.entries(self.fullpath()))
        super(CloudDirTree, self).__init__(rootpath=self.fullpath())
        self._cloud_ids = {}
        self._google_files = set()
        self._sizes = {}
        self.update_from_cache(found)
        return relpath

    def file_size(self, relpath):
        return self._sizes.get(relpath)

    def files_by_name(self):
        # A same-named file's relpath has a DUP_SUFFIX, its name doesn't
        found = collections.defaultdict(list)
        for name, files in super(CloudDirTree, self).files_by_name().items():
            found[name.split(DUP_SUFFIX)[0]] += files
        return found

    def cant_fetch(self, relpath):
        if relpath in self._google_files:
            return "a Google file, which is only in Drive, so it can't be copied to a dir"
        return None

    def copy_notes(self, relpaths):
        google_files = [relpath for relpath in relpaths if relpath in self._google_files]
        if not google_files:
            return []
        return (["%s Google files (Docs, Sheets, ...), which are only in Drive, so they can't be "
                 "copied to a dir: skipped" % (len(google_files),)] + _listed(google_files))

    def fetch_file(self, relpath, local_path):
        """Download the file at relpath to local_path. Raises OSError if it can't."""
        reason = self.cant_fetch(relpath)
        if reason is not None:
            raise OSError("Can't download %s: %s" % (relpath, reason))
        try:
            request = driveapi.service().files().get_media(fileId=self._cloud_ids[relpath])
            with open(local_path, 'wb') as local_file:
                downloader = MediaIoBaseDownload(local_file, request)
                is_done = False
                while not is_done:
                    _, is_done = downloader.next_chunk()
        except HttpError as error:
            raise OSError("Download of %s failed: %s" % (relpath, error))

    def _copy_files(self, files, source, starting, copied):
        """Upload files (of a local dir: their full paths are on the local disk) into the same
        relative paths: first the folders they're in that Drive lacks (_make_folders()), then
        UPLOAD_THREADS files at a time. What Drive says of each upload is added to the tree and the
        cache here, on this thread, as it ends. Ctrl-C starts no more, and waits for the ones under
        way, so the cache has them (and Ctrl-C again doesn't wait: they end on their own)."""
        # Stale until the changes are in the cache, in case it's cut off in the middle
        is_newly_stale = drivecache.mark_stale(self.fullpath())
        self._make_folders(os.path.dirname(file_entry.relpath) for file_entry in files)
        not_started = iter(files)
        under_way = {}
        executor = concurrent.futures.ThreadPoolExecutor(UPLOAD_THREADS)
        try:
            try:
                while True:
                    for file_entry in not_started:
                        starting(file_entry)
                        try:
                            parent_id = self._folder_id(os.path.dirname(file_entry.relpath))
                        except HttpError as error:
                            messages.print_line("Copy failed: %s" % (error,), "red")
                            copied(False)
                            continue
                        under_way[executor.submit(self._upload, file_entry, parent_id)] = file_entry
                        if len(under_way) == UPLOAD_THREADS:
                            break
                    if not under_way:
                        break
                    done, _ = concurrent.futures.wait(
                        under_way, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        # Dropped once it's in the cache, so a Ctrl-C in the middle still waits for it
                        copied(self._uploaded(under_way[future], future))
                        del under_way[future]
            except KeyboardInterrupt:
                if under_way:
                    messages.print_line("Waiting for the %d uploads under way..." % (len(under_way),))
                    for future in concurrent.futures.as_completed(under_way):
                        copied(self._uploaded(under_way[future], future))
                if is_newly_stale:
                    drivecache.unmark_stale(self.fullpath())
                raise
        finally:
            executor.shutdown(wait=False)
        if is_newly_stale:
            drivecache.unmark_stale(self.fullpath())

    def _copy_file(self, file_entry, source):
        """Upload file_entry, as _copy_files() does"""
        results = []
        self._copy_files([file_entry], source, lambda _: None, results.append)
        return results[0]

    def _upload(self, file_entry, parent_id):
        """Upload file_entry into the folder with parent_id, on any thread. Returns what Drive says
        of the new file (its id, ...), with what it was made with. Raises HttpError or OSError if it
        can't."""
        path = file_entry.full_filesystem_path()
        media = MediaFileUpload(path, resumable=os.path.getsize(path) >= RESUMABLE_MIN_SIZE)
        body = {'name': os.path.basename(file_entry.relpath), 'parents': [parent_id]}
        created = driveapi.service().files().create(
            body=body, media_body=media, fields=drivecache.FILE_FIELDS).execute(num_retries=NUM_RETRIES)
        return dict(body, **created)

    def _uploaded(self, file_entry, future):
        """Add file_entry, whose upload (future, of _upload()) ended, to the tree and the cache.
        Returns whether it was uploaded."""
        try:
            md = future.result()
        except (HttpError, OSError) as error:
            messages.print_line("Copy failed: %s" % (error,), "red")
            return False
        drivecache.add(md)
        self.add_file_by_relpath(file_entry.relpath)
        self._cloud_ids[file_entry.relpath] = md['id']
        if 'size' in md:
            self._sizes[file_entry.relpath] = int(md['size'])
        return True

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
            drivecache.add(dict(body, **response))
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
            drivecache.add(dict(body, **created))
            self.create_dir_node_from_relpath_if_not_exists(relpath)
            self._cloud_ids[relpath] = created['id']
        return self._cloud_ids[relpath]

    def removal_notes(self, relpaths):
        lines = []
        folders = self._whole_folders(set(relpaths))
        if folders:
            lines.append("Trashing %d folders whole, all of whose files are picked (checked with "
                         "Drive first, for files the cache doesn't have):" % (len(folders),))
            lines += _listed(folder + '/' for folder in folders)
        google_files = [relpath for relpath in relpaths if relpath in self._google_files]
        if google_files:
            lines.append("Including %d Google files (Docs, Sheets, ...), which are only in Drive:" %
                         (len(google_files),))
            lines += _listed(google_files)
        return lines

    def _remove_files(self, file_entries, starting, removed):
        """Move the files to Drive's trash: the topmost folders all of whose files are picked (see
        _whole_folders()) each as one, once Drive says it has nothing more in them than the tree
        does (it may, if the cache is out of date), and the other files one by one. Trashed as one,
        a folder is restored as one, and leaves no empty folders behind."""
        picked = {file_entry.relpath for file_entry in file_entries}
        folders = self._whole_folders(picked)
        if folders and not dryrun.DRYRUN:
            holding_more = self._folders_holding_more(folders)
            if holding_more is None:
                folders = []
            elif holding_more:
                messages.print_line(
                    "Drive has files in %d folders that the cache doesn't (it's out of date), so "
                    "they're kept, and their picked files are removed one by one: %s" %
                    (len(holding_more), ', '.join(sorted(holding_more)[:MAX_LISTED])), "yellow")
                folders = self._whole_folders(picked, holding_more)
        in_trashed_folders = set()
        for folder in folders:
            folder_files = [relpath for relpath in picked if _is_under(relpath, folder)]
            starting("folder %s/ and its %d files" % (folder, len(folder_files)), len(folder_files))
            if dryrun.DRYRUN or self._trash_folder(folder):
                removed(len(folder_files))
                in_trashed_folders.update(folder_files)
        for file_entry in file_entries:
            if file_entry.relpath not in in_trashed_folders:
                starting(file_entry)
                if dryrun.DRYRUN or self._remove_file(file_entry):
                    removed()

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

    def _trash_folder(self, relpath):
        """Move the folder at relpath, and all that's in it, to Drive's trash, and drop it from the
        tree. Returns whether it was moved."""
        if not self._trash(self._cloud_ids[relpath]):
            return False
        for node in self._tree.subtree(relpath).all_nodes_itr():
            self._cloud_ids.pop(node.identifier, None)
            self._google_files.discard(node.identifier)
        self.remove_node(relpath)
        return True

    def _remove_file(self, file_entry):
        """Move file_entry to Drive's trash, where it can be restored from (for 30 days)"""
        if not self._trash(self._cloud_ids[file_entry.relpath]):
            return False
        self.remove_node(file_entry.relpath)
        del self._cloud_ids[file_entry.relpath]
        self._google_files.discard(file_entry.relpath)
        return True

    def _trash(self, cloud_id):
        """Move the file or folder with cloud_id to Drive's trash (where it can be restored from, for
        30 days), and note it in the cache. Returns whether it was moved (if not, says why)."""
        # Stale until the change is in the cache, in case it's cut off in the middle
        is_newly_stale = drivecache.mark_stale(self.fullpath())
        try:
            driveapi.service().files().update(fileId=cloud_id, body={'trashed': True}).execute(
                num_retries=NUM_RETRIES)
        except HttpError as error:
            messages.print_line("Remove failed: %s" % (error,), "red")
            return False
        drivecache.trash(cloud_id)
        if is_newly_stale:
            drivecache.unmark_stale(self.fullpath())
        return True


def refresh_cache(folder_path):
    """Read the folder at folder_path (a path in Drive, like /eliran; / is all of My Drive) anew from
    Drive, and put it in the cache, in place of what the cache had under it (making the cache, if
    there's none). The folder is found by its path's names, a request a level, then what's in it is
    read, a level of folders at a time (MAX_FOLDERS_PER_QUERY folders a request, one request at a
    time). The rest of the cache isn't read again. Raises HttpError if Drive can't be asked, and
    drivecache.DriveCacheError if it has no such folder (or two); either way (and on Ctrl-C), the
    cache is as it was."""
    folder_path = '/' + '/'.join(paths.components(folder_path))
    root_id = driveapi.service().files().get(fileId='root', fields='id').execute(
        num_retries=NUM_RETRIES)['id']
    # The folders on the way, so the cache has them (as they're named now)
    on_the_way = []
    folder_id = root_id
    messages.print_line("Reading %s from Google Drive..." % (paths.join_cloud(folder_path),))
    path = ''
    for name in paths.components(folder_path):
        path += '/' + name
        found = list(_list("name = '%s' and '%s' in parents and mimeType = '%s' and trashed = false" %
                           (_quoted(name), folder_id, drivecache.FOLDER_MIME_TYPE),
                           drivecache.FILE_FIELDS))
        if not found:
            raise drivecache.DriveCacheError("Google Drive has no folder %s" % (path,))
        if len(found) > 1:
            raise drivecache.DriveCacheError("Google Drive has %d folders named %s: rename them in "
                                             "Drive (a folder's name must be its own)" % (len(found), path))
        on_the_way.append(found[0])
        folder_id = found[0]['id']

    expected_count = drivecache.count_under(folder_path)
    items = []
    folder_ids = [folder_id]
    messages.print_progress(_read_progress(0, expected_count))
    while folder_ids:
        next_folder_ids = []
        for start in range(0, len(folder_ids), MAX_FOLDERS_PER_QUERY):
            query = "(%s) and trashed = false" % (' or '.join(
                "'%s' in parents" % (cloud_id,)
                for cloud_id in folder_ids[start:start + MAX_FOLDERS_PER_QUERY]),)
            for md in _list(query, drivecache.FILE_FIELDS):
                items.append(md)
                if md.get('mimeType') == drivecache.FOLDER_MIME_TYPE:
                    next_folder_ids.append(md['id'])
            messages.print_progress(_read_progress(len(items), expected_count))
        folder_ids = next_folder_ids
    # Done: the count, without the last refresh's
    messages.print_progress(_read_progress(len(items), None))

    drivecache.replace_under(folder_id, on_the_way + items, root_id)
    drivecache.mark_fresh(folder_path)


def _read_progress(count, expected_count):
    """How far reading got, after count files (and folders), expecting about expected_count (or
    None, if not known)"""
    if expected_count and count < expected_count:
        return "Read %s of about %s files and folders (%d%%)" % (
            format(count, ','), format(expected_count, ','), 100 * count // expected_count)
    return "Read %s files and folders" % (format(count, ','),)


def _quoted(name):
    """name, to put between quotes in a Drive query"""
    return name.replace('\\', '\\\\').replace("'", "\\'")


def _list(query, fields='id, parents'):
    """The files and folders (their fields) that Drive lists for query, page by page"""
    page_token = None
    while True:
        response = driveapi.service().files().list(
            q=query, fields='nextPageToken, files(%s)' % (fields,), pageSize=1000,
            pageToken=page_token).execute(num_retries=NUM_RETRIES)
        yield from response.get('files', [])
        page_token = response.get('nextPageToken')
        if not page_token:
            return


def _is_under(relpath, folder):
    return relpath.startswith(folder + '/')


def _listed(items):
    """Lines listing the first MAX_LISTED of items, indented, and how many more there are"""
    items = list(items)
    lines = ["  %s" % (item,) for item in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        lines.append("  (and %d more)" % (len(items) - MAX_LISTED,))
    return lines
