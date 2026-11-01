"""Exploring an archive (see archives.py) in a picker, as a tree of what's in it, each file's size and
date beside it: to look through, nothing's unpacked or changed."""
import posixpath

from dirdelta import archives
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import picker
from dirdelta import text

# The file pickers' key, on a selected archive
KEY = 'e'
KEY_NAME = 'e'
KEY_HINT = (KEY, 'explore a zip')


def explore(relpath, files, local_path, label=None):
    """Explore the file at relpath, if it's one of files and an archive (else it says so): local_path()
    is where it is on this machine, which may download it"""
    if relpath not in files or not archives.is_archive(relpath):
        messages.show("Not a zip", ["Select a .zip file to look in it."], dryrun.label())
        return
    found, error = None, None
    # A Drive file is downloaded first, which Ctrl-C stops
    with messages.progress_screen("Looking in %s" % (posixpath.basename(relpath),), dryrun.label(), wait=False):
        try:
            found = archives.members(local_path())
        except (archives.ArchiveError, OSError) as failure:
            error = failure
    if error is not None:
        messages.show("Can't look in %s" % (relpath,), [str(error)], dryrun.label(), 'red')
    elif found is not None and not found:
        messages.show(relpath, ["It's an empty zip."], dryrun.label())
    elif found:
        _show(relpath, found, label)


def _show(relpath, found, label):
    total = sum(member.size for member in found)
    previews = {member.relpath: _preview(member) for member in found}
    header = "In %s: %s, %s in all. To look through: nothing's unpacked." % (
        relpath, text.files(len(found)), text.format_size(total))
    with picker.place("Zip %s" % (posixpath.basename(relpath),)):
        picker.view_files(posixpath.basename(relpath), [member.relpath for member in found], header=header,
                          previews=previews, label=label, key_hints=[('Enter', 'back'), ('q', 'back')])


def _preview(member):
    lines = ["Size: %s" % (text.format_size(member.size),),
             "Compressed: %s" % (text.format_size(member.compressed_size),)]
    if member.modified is not None:
        lines.append("Changed: %s" % (member.modified.strftime('%Y-%m-%d %H:%M'),))
    return lines
