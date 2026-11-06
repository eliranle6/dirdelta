"""A job's files, each with its tag and hash"""
from dirdelta.screens.hashes_screen.marks import Marks
from dirdelta.screens.hashes_screen.names import HELP_LINES
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text


def view_files(job):
    """Show the job's replica's files, each with its mark (hashed, being hashed, not yet), and its
    hash beside it, until the user quits"""
    relpaths = job.files()
    if not relpaths:
        messages.show("No files", ["%s has no files (as of its last listing)." % (job.root,)], dryrun.label())
        return
    marks = Marks(job, relpaths, [job])
    header = ("%s's files, hashed or not, as they're hashed. / searches their tags too, e.g. /not hashed "
              "for the ones left." % (job.root,))
    try:
        picker.view_files(job.root, relpaths, header=header, shown_as=marks, help_lines=HELP_LINES,
                          key_hints=[('Enter', 'back'), ('q', 'back')],
                          on_selection=lambda selection, send: _send_hash_previews(job, selection, send))
    finally:
        marks.close()


def _send_hash_previews(job, selection, send):
    """Send the selected file's preview: its size, and its hash, or that it's not hashed yet"""
    relpath = None
    while True:
        moved_to = selection.wait_next(1)
        relpath = moved_to if moved_to is not None else relpath
        if relpath is None:
            continue
        size = job.size_of(relpath)
        lines = ["This one: %s" % (text.format_size(size),)] if size is not None else []
        value = job.hash_of(relpath)
        if value is not None:
            lines += ["SHA-1:", "  " + value]
        elif job.is_being_hashed(relpath):
            lines.append("Being hashed now")
        elif relpath in job.failed():
            lines.append("Couldn't be hashed (unreadable, or changing while read)")
        elif size is not None:
            lines.append("Not hashed yet" + ("" if job.is_started() else " (hashing is paused)"))
        send({relpath: lines}, default=[])
