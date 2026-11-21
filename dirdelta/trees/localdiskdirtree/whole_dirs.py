"""The dirs all of whose files are being removed, found on the disk itself (whole_dirs()): each is removed as one
(one move to the trash, restored as one, rather than a move for each of its files), only if nothing else is in it:
not a file the comparison left out (junk, dirdelta's meta/), nor a link, nor a file it can't read"""
import os


def whole_dirs(rootpath, picked, kept=lambda dirpath: False):
    """The topmost dirs under rootpath (relpaths, not the root itself) with a picked file (of picked, relpaths) in them,
    all of whose contents are picked files, as the disk has them now: nothing in them would be left. A kept(relpath)
    dir, and those it's in, never are."""
    picked = set(picked)
    tops = {relpath.split('/', 1)[0] for relpath in picked if '/' in relpath}
    # Each dir's (whether it has a picked file, whether all that's in it is picked)
    found = {}
    for top in tops:
        unreadable = set()
        for dirpath, dirnames, filenames in os.walk(os.path.join(rootpath, top), topdown=False,
                                                     onerror=lambda error: unreadable.add(error.filename)):
            relpath = os.path.relpath(dirpath, rootpath)
            files = [os.path.join(relpath, name) for name in filenames]
            # (A link to a dir is listed as a dir, but not walked into: it isn't picked, so it's kept)
            links = [name for name in dirnames if os.path.islink(os.path.join(dirpath, name))]
            subdirs = [os.path.join(relpath, name) for name in dirnames if name not in links]
            has_picked = any(path in picked for path in files) or any(found.get(sub, (False, False))[0] for sub in subdirs)
            whole = (not links and dirpath not in unreadable and not kept(relpath) and
                     all(path in picked for path in files) and all(found.get(sub, (False, False))[1] for sub in subdirs))
            found[relpath] = (has_picked, whole)
    # The topmost whole ones: none of the dirs they're in is
    chosen = []
    for relpath in sorted(found, key=lambda relpath: relpath.count('/')):
        has_picked, whole = found[relpath]
        if has_picked and whole and not any(relpath.startswith(top + '/') for top in chosen):
            chosen.append(relpath)
    return sorted(chosen)
