"""Uploading it again as it changes, while a sync goes on (Uploader, kept())"""
import contextlib
import threading

from googleapiclient.errors import HttpError

from dirdelta.drive import drivecache
from dirdelta.drive.drivemeta.checking import check
from dirdelta.drive.drivemeta.names import FILE_NAME, UPLOAD_INTERVAL, USED
from dirdelta.drive.drivemeta.uploading import upload
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


class Uploader(object):
    """Uploads the cache's list of a Drive replica's folder (see upload()) whenever it changed
    since the last upload, every UPLOAD_INTERVAL seconds at most, on a thread of its own, from
    start() until stop() (which uploads once more, if it changed). What goes wrong is written to
    picker.ERRORS_LOG (and tried again next time), not on the screen."""
    def __init__(self, folder_path):
        self.folder_path = folder_path
        self._stopping = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stopping.wait(UPLOAD_INTERVAL):
            try:
                self.upload_if_changed()
            except Exception:
                picker.log_error()

    def is_changed(self):
        """Whether the cache's list changed since it was last uploaded (or it never was)"""
        updated = drivecache.updated(self.folder_path)
        uploaded = drivecache.uploaded(self.folder_path)
        if uploaded is None:
            return True
        return updated is not None and (uploaded.get('as_of') is None or updated > uploaded['as_of'])

    def upload_if_changed(self):
        """Upload it, if it changed since (not in a dry run). Returns whether it was uploaded."""
        with self._lock:
            if dryrun.DRYRUN or not self.is_changed():
                return False
            upload(self.folder_path)
            return True

    def stop(self):
        """Stop, uploading it once more if it changed since. Raises as upload() does."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join()
        return self.upload_if_changed()


@contextlib.contextmanager
def kept(replicas):
    """While a sync or a sort of replicas ([(a replica's path, its tree, or None if it's not made
    yet)]) goes on: each Drive one's list is checked against the copy in Drive first (check(); a
    tree is rebuilt from the cache if that was newer), and uploaded (an Uploader) as it changes, and
    once more at the end"""
    uploaders = []
    for path, tree in replicas:
        if not paths.is_cloud_path(path):
            continue
        folder_path = paths.path_in_cloud(path)
        try:
            if check(folder_path) == USED:
                if tree is not None:
                    tree.reload_from_cache()
                messages.print_line("Using the file list of %s kept in it (%s/%s), newer than this machine's" %
                                    (path, paths.META_DIR, FILE_NAME))
        except (HttpError, OSError, drivecache.DriveCacheError) as error:
            messages.print_line("Couldn't read the file list kept in %s: %s" % (path, error), 'red')
        uploader = Uploader(folder_path)
        uploader.start()
        uploaders.append((path, uploader))
    try:
        yield
    finally:
        for path, uploader in uploaders:
            if not dryrun.DRYRUN and uploader.is_changed():
                messages.print_line("Keeping %s's file list in it (%s/%s)..." % (path, paths.META_DIR, FILE_NAME))
            try:
                uploader.stop()
            except (HttpError, OSError) as error:
                messages.show("Couldn't keep the file list in %s" % (path,),
                              ["Uploading it to %s/%s failed: %s" % (paths.META_DIR, FILE_NAME, error),
                               "It's uploaded at the next sync of it."], dryrun.label(), 'red')
