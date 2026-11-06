"""What dirdelta changes in Drive, put in the cache"""
from dirdelta.drive.drivecache.database import opened, put_row, root_of, set_root
from dirdelta.drive.drivecache.reading import parsefile
from dirdelta.trees import paths


def clean_path(folder_path):
    return '/' + '/'.join(paths.components(folder_path))


def under(folder_id, left_out=()):
    """The metadata of what the cache has under the folder with folder_id (the files and folders in
    it, and in those, ...), each folder before what's in it, without what's under the folders whose
    ids are in left_out (nor them)"""
    id_child_map, id_md_map, _ = parsefile()
    found = []
    stack = [folder_id]
    while stack:
        for child_id in id_child_map.get(stack.pop(), []):
            if child_id in left_out:
                continue
            found.append(id_md_map[child_id])
            stack.append(child_id)
    return found


def add(md):
    """Add a file or folder that was made in Drive (its metadata, as the Drive API gives it)"""
    with opened() as db:
        put_row(db, md)


def trash(cloud_id):
    """Note that the file or folder with the id was moved to the trash"""
    with opened() as db:
        db.execute('DELETE FROM files WHERE id = ?', (cloud_id,))


def replace_under(folder_id, items, my_drive_id):
    """Replace what the cache has under the folder with folder_id (the files and folders in it, and
    in those, ...) with items (their metadata, as the Drive API lists them, FILE_FIELDS), e.g. what
    Drive lists under it now. The folder's own row stays. With no cache, or one that doesn't say
    what My Drive is, make one, with My Drive's root folder's id (my_drive_id) and items. All at once:
    it's never left half written."""
    with opened() as db:
        if root_of(db) is None:
            db.execute('DELETE FROM files')
            set_root(db, my_drive_id)
        stack = [folder_id]
        while stack:
            children = [row[0] for row in db.execute('SELECT id FROM files WHERE parent = ?', (stack.pop(),))]
            db.executemany('DELETE FROM files WHERE id = ?', [(child,) for child in children])
            stack.extend(children)
        for md in items:
            put_row(db, md)
