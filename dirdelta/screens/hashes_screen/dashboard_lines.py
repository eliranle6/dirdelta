"""The dashboard's lines of each replica's hashing and Drive's hashes"""
from dirdelta.hashes import hashing
from dirdelta.known import replicainfo
from dirdelta.screens.hashes_screen.names import (_BAR,
    _FILES,
    _INFO,
    _RESCAN,
    _STATE,
    _TOGGLE,
    _files,
    is_local)
from dirdelta.screens.hashes_screen.waiting import progress_line
from dirdelta.trees import paths
from dirdelta.ui import picker
from dirdelta.util import text


def _job_of(name, tree):
    """The hashing job of the local replica named name (its tree's displayname, or its path), if any"""
    if paths.is_cloud_path(name) or (tree is not None and not is_local(tree)):
        return None
    return hashing.job_for(tree.fullpath() if tree is not None else name)


def _cache_age(path):
    """'; Drive's file list cached DD.MM.YYYY HH:MM' (when the cache's list of the Drive replica at
    path was last updated, see replicainfo.cache_time()), or ''"""
    read = replicainfo.cache_time(path)
    return "; Drive's file list cached %s" % (read.strftime('%d.%m.%Y %H:%M'),) if read else ""


def _jobs_shown(items, names):
    """The dashboard's options of the local replicas' (of items, [(name, tree or None)]) files and
    hashing, as they're shown now; names: their short names, by name (see replicanames.short_names())"""
    shown = {}
    for name, job in _jobs_by_name(items).items():
        progress = job.progress()
        if progress.state in (hashing.NOT_SCANNED, hashing.SCANNING):
            shown[(_INFO, name)] = picker.Skipped("  Listing its files...")
            shown[(_BAR, name)] = picker.Skipped("  Hashes: -")
        else:
            shown[(_INFO, name)] = picker.Skipped("  %s, %s" % (_files(progress.nr_files),
                                                                   text.format_size(progress.size)))
            shown[(_BAR, name)] = picker.Skipped("  Hashes: " + progress_line(progress))
        state = _state_text(job, progress)
        if progress.current:
            state += ": now %s%s" % (progress.current[0], " (and %d more)" % (len(progress.current) - 1,)
                                     if len(progress.current) > 1 else "")
        if progress.nr_failed:
            state += "; %s couldn't be hashed (unreadable, or changing while read)" % (_files(progress.nr_failed),)
        shown[(_STATE, name)] = picker.Skipped("  " + state)
        short = names.get(name, job.name())
        if progress.state == hashing.DONE:
            shown[(_TOGGLE, name)] = picker.Disabled("  Pause hashing %s: it's all hashed" % (short,))
        elif job.is_started():
            shown[(_TOGGLE, name)] = "  Pause hashing %s" % (short,)
        else:
            shown[(_TOGGLE, name)] = "  %s hashing %s" % ("Resume" if progress.is_paused else "Start", short)
        shown[(_FILES, name)] = "  See its files: which are hashed, and which not yet"
        shown[(_RESCAN, name)] = "  Look for new or changed files in it (after changes outside dirdelta)"
    return shown


def _jobs_by_name(items):
    """{name: job} of the local replicas (of items, [(name, tree or None)]) that have a hashing job"""
    found = {}
    for name, tree in items:
        job = _job_of(name, tree)
        if job is not None:
            found[name] = job
    return found


def _state_text(job, progress):
    if job.error:
        return "Couldn't list its files: %s" % (job.error,)
    if progress.state == hashing.DONE:
        return "All hashed ✓"
    if progress.state in (hashing.NOT_SCANNED, hashing.SCANNING):
        return "Listing its files"
    if job.is_started():
        workers = 1 if job.max_workers == 1 else hashing.nr_workers()
        return "Hashing, %d thread%s%s" % (workers, "s" if workers > 1 else "",
                                            " (a spinning disk: one at a time)" if job.max_workers == 1 else "")
    return "Paused" if progress.is_paused else "Not started"


def _drive_lines(cloud):
    """How many files a cloud replica has, their size, and the dashboard's lines of it: how many of
    its files Drive gave SHA-1s of (and SHA-256s), and what to do about the rest"""
    nr_files = nr_sha1 = nr_sha256 = size = 0
    for file_entry in cloud.iter_files():
        known = cloud.known_hashes(file_entry.relpath)
        nr_files += 1
        size += cloud.file_size(file_entry.relpath) or 0
        nr_sha1 += 'sha1' in known
        nr_sha256 += 'sha256' in known
    first = "  Drive's hashes, none read here: SHA-1 of %s of %s, SHA-256 of %s" % (
        "{:,}".format(nr_sha1), _files(nr_files), "{:,}".format(nr_sha256))
    if nr_sha256 < nr_files:
        nr_without = nr_files - nr_sha256
        note = "  %s %s no hash: Google's own files (Docs, Sheets...)" % (_files(nr_without), "has" if nr_without == 1 else "have")
    else:
        note = "  All its files have Drive's hashes"
    return nr_files, size, first, note
