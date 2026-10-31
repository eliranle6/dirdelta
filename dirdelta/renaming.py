"""Renaming a file or dir where it is, as vim's cc does: the file pickers' cc (of a sync, an inbox's
sort, and the dir picker of where in the sorted tree files go) asks for the selected one's new
name, starting as its own, and renames it (in a dry run, says what it would do)."""
import posixpath

from dirdelta import dryrun
from dirdelta import messages

# The pickers' key, pressed twice (picker.pick_files(twice_keys=KEY)), and the key it's returned as
KEY = 'c'
PRESSED = KEY * 2
KEY_HINT = ('cc', 'rename')

# Renamed is (its new relpath, the moves of its files: [(relpath, new_relpath)])


def rename(tree, relpath, label=None):
    """Ask for a new name of tree's (a DirTree's) file or dir at relpath, and rename it: a dir as
    one, with all in it. Returns (its new relpath, the moves of the files: [(relpath, new_relpath)],
    the ones done; in a dry run, the ones it would do); or None if it wasn't renamed (no name, the
    same name, or one that can't be; the root)."""
    if not relpath:
        messages.show("Can't rename it", ["%s is the tree's root: rename a file or dir in it." % (tree.displayname(),)],
                      label or dryrun.label())
        return None
    if not tree._exists(relpath):
        messages.show("Can't rename it", ["%s isn't there (anymore?)." % (relpath,)], label or dryrun.label(), 'red')
        return None
    is_dir = not tree.has_file(relpath)
    name = posixpath.basename(relpath)
    files = tree._files_under(relpath) if is_dir else [relpath]
    reason = next((tree.cant_move(file) for file in files if tree.cant_move(file) is not None), None)
    if reason is not None and not is_dir:
        messages.show("Can't rename it", ["%s can't be renamed: %s." % (relpath, reason)], label or dryrun.label(), 'red')
        return None
    where = posixpath.join(tree.displayname(), posixpath.dirname(relpath))
    new_name = messages.ask("Rename %s%s" % (name, '/' if is_dir else ''),
                            ["Renaming %s %s in %s/" % ("the dir" if is_dir else "the file", name, where),
                             "Its new name (Enter keeps it; an empty one, or Ctrl-C, goes back):"],
                            "> ", name, label or dryrun.label())
    if new_name is None or new_name == name:
        return None
    if '/' in new_name or new_name in ('.', '..'):
        messages.show("Not a name", ["%r can't be a name: it's a name, without '/'." % (new_name,)],
                      label or dryrun.label(), 'red')
        return None
    new_relpath = posixpath.join(posixpath.dirname(relpath), new_name)
    if tree._exists(new_relpath):
        messages.show("There already", ["%s has %s already." % (where, new_name)], label or dryrun.label(), 'red')
        return None
    moves = [(file, new_relpath + file[len(relpath):]) for file in files]
    is_renamed = False
    # Stopped (Ctrl-C) before it's done, nothing is said done
    done = []
    title = "Renaming %s to %s%s" % (name, new_name, " (a dry run)" if dryrun.DRYRUN else "")
    # Waiting for Enter, as a copy's or a removal's, so how it went is read
    with messages.progress_screen(title, dryrun.label()):
        if not is_dir:
            done = tree.move_files(moves)
        elif dryrun.DRYRUN:
            messages.print_line("Dry run, not renaming the dir %s/ to %s/, with its %d files" %
                                (relpath, new_relpath, len(files)))
            done = []
        else:
            messages.print_line("Renaming the dir %s/ to %s/, with its %d files" % (relpath, new_relpath, len(files)))
            # An empty one is renamed too, with no files' moves
            is_renamed = tree._move_dir(relpath, new_relpath)
            done = moves if is_renamed else []
    if dryrun.DRYRUN:
        return new_relpath, moves
    return (new_relpath, done) if done or (is_dir and is_renamed) else None
