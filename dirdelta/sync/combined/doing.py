"""Doing a combined tree's plan: on one progress screen, in an order where being stopped (Ctrl-C) or
failing loses nothing: the moves (within a replica), the copies, then the replacements (the old versions to the trash, or kept by
Drive), then the removals (a local replica's to the trash)"""
import contextlib
import os

from dirdelta.sync import replica_ops
from dirdelta.trees import entries
from dirdelta.ui import messages
from dirdelta.util import dryrun


def do(plan, replica_a, replica_b, changes=None, names=None):
    """Do the plan (see plan.Plan) to replica_a and replica_b, noting what was done live in changes (a
    log_entries.Changes, if given); names: {replica: what the screens call it} (else their paths)"""
    names = names or {}
    name_a, name_b = (names.get(replica, replica.displayname()) for replica in (replica_a, replica_b))
    steps = [(_move, plan.move_in_b, replica_b, None, False), (_move, plan.move_in_a, replica_a, None, False),
             (_copy, plan.copy_to_b, replica_a, replica_b, False), (_copy, plan.copy_to_a, replica_b, replica_a, False),
             (_copy, plan.replace_b, replica_a, replica_b, True), (_copy, plan.replace_a, replica_b, replica_a, True),
             (_remove, plan.remove_from_a, replica_a, None, False), (_remove, plan.remove_from_b, replica_b, None, False)]
    title = "Syncing %s and %s" % (name_a, name_b) + (" (a dry run)" if dryrun.DRYRUN else "")
    with messages.progress_screen(title, dryrun.label()):
        for step, relpaths, replica, other, is_replacing in steps:
            if not relpaths:
                continue
            # The trees stop on Ctrl-C, and say so: then so does the rest
            if messages.is_stopped():
                messages.print_line("What's left isn't done.")
                return
            if step is _copy:
                _copy(relpaths, replica, other, changes, is_replacing, names)
            else:
                step(relpaths, replica, changes, names)
        messages.print_line("Done: a dry run, nothing changed." if dryrun.DRYRUN else "Done.", 'green')


def _entries(relpaths, replica):
    """The replica's files at relpaths, as the trees copy and remove them"""
    return [entries.FileEntry(os.path.basename(relpath), relpath, os.path.join(replica.fullpath(), relpath))
            for relpath in relpaths]


def _name(replica, names):
    return (names or {}).get(replica, replica.displayname())


def _copy(relpaths, src, dst, changes, is_replacing=False, names=None):
    """Copy src's files at relpaths to dst (is_replacing: over dst's other versions of them)"""
    messages.print_line("%s %s from %s to %s" % ("Replacing with" if is_replacing else "Copying",
                                                 replica_ops.files_text(len(relpaths)), _name(src, names),
                                                 _name(dst, names)))
    with dst.replacing() if is_replacing else contextlib.nullcontext():
        dst.copy_in(_entries(relpaths, src), src)
    if not dryrun.DRYRUN and changes is not None:
        done = [relpath for relpath in relpaths if dst.has_file(relpath)]
        changes.note(dst.displayname(), 'copied', len(done), src.displayname())


def _move(moves, replica, changes, names=None):
    """Move the replica's files, each of moves (relpath, new_relpath), a whole dir's as one"""
    messages.print_line("Moving %s in %s" % (replica_ops.files_text(len(moves)), _name(replica, names)))
    done = replica.move_files(moves)
    if not dryrun.DRYRUN and changes is not None:
        changes.note(replica.displayname(), 'moved', len(done))


def _remove(relpaths, replica, changes, names=None):
    """Remove the replica's files at relpaths (a local one's to the trash)"""
    messages.print_line("Removing %s from %s" % (replica_ops.files_text(len(relpaths)), _name(replica, names)))
    with replica.trashing() if replica_ops.is_local(replica) else contextlib.nullcontext():
        replica.remove_files(_entries(relpaths, replica))
    if not dryrun.DRYRUN and changes is not None:
        done = [relpath for relpath in relpaths if not replica.has_file(relpath)]
        changes.note(replica.displayname(), 'removed', len(done))
