"""The screens of hashing local replicas' files (hashing.py): whether to hash a replica's files
when it's opened (offer()), and waiting for it (wait()); the dashboard (dashboard()): each replica's
progress, pausing and resuming it, and its files, hashed or not; and what the file pickers show of it
(Marks): a label for each replica on the bottom line, in a color by how far it got (red, orange,
yellow, then green once it's all hashed), and a mark before each file's name."""
import os
import shutil
import threading
import time

from dirdelta import clouddirtree
from dirdelta import dryrun
from dirdelta import elsewhere
from dirdelta import hashcache
from dirdelta import hashing
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import picker

# The file pickers' key that shows the dashboard
KEY = '#'
# What the file pickers' headers say of it
KEY_HELP = ("%s: hashing (pause, resume, which files); %s hashed, %s being hashed, %s not yet." %
            (KEY, hashing.HASHED_MARK, hashing.HASHING_MARK, hashing.NOT_HASHED_MARK))

NOTHING = "Nothing: go back"
NOT_NOW = "Not now: go on, matching files by their names and sizes (%s in the file pickers starts it)" % (KEY,)
HASH_AND_WAIT = "Hash them now, and wait (recommended; Ctrl-C goes on, hashing in the background)"
HASH_IN_BACKGROUND = "Hash them in the background, and go on"
# How often the wait's progress line changes, in seconds
WAIT_INTERVAL = 0.5


def _files(count):
    return "1 file" if count == 1 else "{:,} files".format(count)


def is_local(replica):
    return isinstance(replica, localdiskdirtree.LocalDiskDirTree)


def prepare(replicas):
    """The jobs of the local replicas (of replicas, trees), each scanned (its files listed, and which
    are hashed found), once"""
    jobs = []
    for replica in replicas:
        if not is_local(replica):
            continue
        job = hashing.job(replica.fullpath(), replica.max_depth)
        if job.progress().state == hashing.NOT_SCANNED:
            if replica.file_stamps is not None:
                # Listed by the replica's scan already
                job.scan(replica.file_stamps)
            else:
                messages.print_line("Listing the files of %s, to find their hashes..." % (job.root,))
                job.scan()
        if job not in jobs:
            jobs.append(job)
    return jobs


def jobs_of(replicas):
    """The jobs of the local replicas (of replicas, trees) that have one"""
    found = []
    for replica in replicas:
        job = hashing.job_for(replica.fullpath()) if is_local(replica) else None
        if job is not None and job not in found:
            found.append(job)
    return found


def offer(jobs):
    """Ask whether to hash the files of the jobs' replicas that aren't all hashed (and aren't being
    hashed): nothing (going back), not now, now, waiting for it (recommended), or in the background.
    The ones all hashed are started (so files that come later are hashed too). Returns whether to
    go on (False: the user chose nothing, or quit)."""
    left = []
    for job in jobs:
        progress = job.progress()
        if progress.state == hashing.DONE:
            job.start()
        elif not job.is_started() and progress.state != hashing.NOT_SCANNED:
            left.append((job, progress))
    if not left:
        return True
    lines = ["Hash the files? Hashes find a file by its contents: moved or renamed (any size), or a copy.",
             "Each file is read once, and its hash kept for next time. Not hashed yet:"]
    for job, progress in left:
        # The path last, so a long one doesn't hide the rest
        lines.append("  %s of %s left (%s of %s): %s" % (
            "{:,}".format(progress.nr_files - progress.nr_done), _files(progress.nr_files),
            elsewhere.format_size(progress.size - progress.size_done), elsewhere.format_size(progress.size),
            job.root))
    lines += ["Waiting for it before comparing is recommended. Until it's done, files are matched",
              "by their names and sizes, and compared when selected."]
    answer = picker.pick_option([NOTHING, NOT_NOW, HASH_AND_WAIT, HASH_IN_BACKGROUND],
                                header='\n'.join(lines))
    if answer in (None, NOTHING):
        return False
    if answer in (HASH_AND_WAIT, HASH_IN_BACKGROUND):
        for job, _ in left:
            job.start()
    if answer == HASH_AND_WAIT:
        wait([job for job, _ in left])
    return True


def total(jobs):
    """The jobs' progress together (a hashing.Progress)"""
    progresses = [job.progress() for job in jobs]
    states = {progress.state for progress in progresses}
    rates = [progress.rate for progress in progresses if progress.rate]
    return hashing.Progress(
        hashing.DONE if states == {hashing.DONE} else hashing.HASHING,
        sum(progress.nr_files for progress in progresses), sum(progress.nr_done for progress in progresses),
        sum(progress.size for progress in progresses), sum(progress.size_done for progress in progresses),
        [current for progress in progresses for current in progress.current],
        sum(rates) if rates else None, sum(progress.nr_failed for progress in progresses),
        all(progress.is_paused for progress in progresses), any(progress.is_started for progress in progresses))


def progress_line(progress):
    """A line of how far hashing got: its bar, %, files, size, speed and time left"""
    line = "%s %d%%  %s of %s, %s of %s" % (
        hashing.bar(progress), hashing.percent(progress), "{:,}".format(progress.nr_done),
        _files(progress.nr_files), elsewhere.format_size(progress.size_done), elsewhere.format_size(progress.size))
    if progress.rate and progress.is_started and progress.state != hashing.DONE:
        line += ", %s/s" % (elsewhere.format_size(progress.rate),)
        left = hashing.time_left(progress)
        if left is not None and progress.state != hashing.DONE:
            line += ", ~%s left" % (hashing.format_duration(left),)
    return line


def wait(jobs):
    """Show how far the jobs got, on a screen, until they're done, or Ctrl-C (they go on, in the
    background)"""
    names = ", ".join(job.root for job in jobs)
    with messages.progress_screen("Ctrl-C goes on, hashing in the background: hashing the files of %s" % (names,),
                                  dryrun.label(), is_stoppable=False, wait=False):
        messages.print_line("Each file is read once, and its hash kept. Ctrl-C goes on while it hashes in the "
                            "background (%s in the file pickers shows how far it got)." % (KEY,))
        messages.print_line("")
        try:
            while True:
                progress = total(jobs)
                if progress.state == hashing.DONE:
                    break
                width = shutil.get_terminal_size().columns - 1
                line = progress_line(progress)
                if progress.current:
                    line += "  " + progress.current[0]
                messages.print_progress(line[:width])
                time.sleep(WAIT_INTERVAL)
        except KeyboardInterrupt:
            messages.print_line("")
            messages.print_line("Going on: hashing goes on in the background.")
            return
        messages.print_line("")
        messages.print_line("All hashed: %s" % (progress_line(progress),), 'green')


# The dashboard's options, made unique by the replica's root (shown_as says what they show)
_HEADING = "── %s ──"
_BAR = "  bar %s"
_STATE = "  state %s"
_TOGGLE = "  toggle %s"
_FILES = "  See which of its files are hashed %s"
_RESCAN = "  rescan %s"
_DRIVE = "  drive %s"
_DRIVE_NOTE = "  drive note %s"
BACK = "Back"


def dashboard(jobs, clouds=()):
    """The hashing dashboard: for each job, how far it got (a bar, files, sizes, speed, time left,
    the files being hashed now), pausing or resuming it, its files (hashed or not), and scanning it
    again; for each cloud replica (of clouds, CloudDirTrees), how many of its files' hashes Drive
    gave. Until Back."""
    selected = None
    while True:
        options, shown = [], {}
        for job in jobs:
            root = job.root
            options += [_HEADING % (root,), _BAR % (root,), _STATE % (root,), _TOGGLE % (root,),
                        _FILES % (root,), _RESCAN % (root,)]
        drive_lines = {}
        for cloud in clouds:
            name = cloud.displayname()
            drive_lines[name] = _drive_lines(cloud)
            options += [_HEADING % (name,), _DRIVE % (name,), _DRIVE_NOTE % (name,)]
            shown[_HEADING % (name,)] = picker.Disabled(_HEADING % ("%s (Google Drive)" % (name,),))
            shown[_DRIVE % (name,)] = picker.Disabled(drive_lines[name][0])
            shown[_DRIVE_NOTE % (name,)] = picker.Disabled(drive_lines[name][1])
        options.append(BACK)
        header = ("Hashing the local replicas' files (SHA-1, as Drive's), each read once, at the lowest "
                  "priority\nThe hashes are kept in %s" % (hashcache.CACHE_FILE,))
        if selected is None:
            # The first that can be picked
            first = _jobs_shown(jobs)
            selected = next((option for option in options
                             if option.startswith(("  toggle", "  See")) and
                             not isinstance(first.get(option), picker.Disabled)), BACK)
        option = picker.pick_option(options, header=header, shown_as=lambda: dict(
            shown, **_jobs_shown(jobs), **{'': picker.status(hashing.status_parts(jobs))}), selected=selected)
        if option in (None, BACK):
            return
        selected = option
        for job in jobs:
            if option == _TOGGLE % (job.root,):
                if job.is_started():
                    job.pause()
                else:
                    job.start()
            elif option == _FILES % (job.root,):
                view_files(job)
            elif option == _RESCAN % (job.root,):
                job.scan_in_background()


def _jobs_shown(jobs):
    """The dashboard's options of the jobs, as they're shown now"""
    shown = {}
    for job in jobs:
        root, progress = job.root, job.progress()
        shown[_HEADING % (root,)] = picker.Disabled(_HEADING % (root,))
        if progress.state in (hashing.NOT_SCANNED, hashing.SCANNING):
            shown[_BAR % (root,)] = picker.Disabled("  Listing its files...")
        else:
            shown[_BAR % (root,)] = picker.Disabled("  " + progress_line(progress))
        state = _state_text(job, progress)
        if progress.current:
            state += ": now %s%s" % (progress.current[0], " (and %d more)" % (len(progress.current) - 1,)
                                     if len(progress.current) > 1 else "")
        if progress.nr_failed:
            state += "; %s couldn't be hashed (unreadable, or changing while read)" % (_files(progress.nr_failed),)
        shown[_STATE % (root,)] = picker.Disabled("  " + state)
        if progress.state == hashing.DONE:
            shown[_TOGGLE % (root,)] = picker.Disabled("  Pause hashing %s: it's all hashed" % (job.name(),))
        elif job.is_started():
            shown[_TOGGLE % (root,)] = "  Pause hashing %s" % (job.name(),)
        else:
            shown[_TOGGLE % (root,)] = "  %s hashing %s" % ("Resume" if progress.is_paused else "Start", job.name())
        shown[_FILES % (root,)] = "  See its files: %s hashed, %s being hashed, %s not yet" % (
            hashing.HASHED_MARK, hashing.HASHING_MARK, hashing.NOT_HASHED_MARK)
        shown[_RESCAN % (root,)] = "  Look for new or changed files in it (after changes outside dirdelta)"
    return shown


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
    """The dashboard's lines of a cloud replica: how many of its files Drive gave SHA-1s of (and
    SHA-256s), and what to do about the rest"""
    nr_files = nr_sha1 = nr_sha256 = 0
    for file_entry in cloud.iter_files():
        known = cloud.known_hashes(file_entry.relpath)
        nr_files += 1
        nr_sha1 += 'sha1' in known
        nr_sha256 += 'sha256' in known
    first = "  Drive's hashes, none read here: SHA-1 of %s of %s, SHA-256 of %s" % (
        "{:,}".format(nr_sha1), _files(nr_files), "{:,}".format(nr_sha256))
    if nr_sha1 < nr_sha256:
        note = ("  %s have no SHA-1 in the cache (from before 29.10.2026): reading its folders anew "
                "from Drive gets them" % (_files(nr_sha256 - nr_sha1),))
    elif nr_sha256 < nr_files:
        note = "  %s have no hash: Google's own files (Docs, Sheets...)" % (_files(nr_files - nr_sha256),)
    else:
        note = "  All its files have Drive's hashes"
    return first, note


def view_files(job):
    """Show the job's replica's files, each with its mark (hashed, being hashed, not yet), and its
    hash beside it, until the user quits"""
    relpaths = job.files()
    if not relpaths:
        messages.show("No files", ["%s has no files (as of its last listing)." % (job.root,)], dryrun.label())
        return
    marks = Marks(job, relpaths, [job])
    header = ("%s's files: %s hashed, %s being hashed, %s not yet (as they're hashed). / searches the marks "
              "too, e.g. /%s for the ones left." % (job.root, hashing.HASHED_MARK, hashing.HASHING_MARK,
                                                     hashing.NOT_HASHED_MARK, hashing.NOT_HASHED_MARK))
    try:
        picker.view_files(job.root, relpaths, header=header, shown_as=marks,
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
        lines = ["This one: %s" % (elsewhere.format_size(size),)] if size is not None else []
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


class Marks(object):
    """A picker's shown_as (see picker.pick_files()) of a job's files (relpaths, of its replica's):
    each file's name after its mark (hashed, being hashed, not yet; see hashing.mark()), as it
    changes; and the status, a label of each of status_jobs (see hashing.status_parts()), and then
    extra() (more parts, [(text, color)]), if given. close() it once the picker is gone."""

    def __init__(self, job, relpaths, status_jobs, extra=None):
        self._job = job
        self._relpaths = relpaths
        self._status_jobs = status_jobs
        self._extra = extra
        self._lock = threading.Lock()
        # The files whose marks may have changed since they were last shown (None: all of them),
        # and the ones being hashed when they were
        self._changed = None
        self._current = set()
        self._wanted = set(relpaths) if job is not None else set()
        if job is not None:
            job.subscribe(self._on_hashed)

    def _on_hashed(self, relpath, hashes):
        if relpath in self._wanted:
            with self._lock:
                if self._changed is not None:
                    self._changed.add(relpath)

    def close(self):
        """No more marks to change"""
        if self._job is not None:
            self._job.unsubscribe(self._on_hashed)

    def __call__(self):
        shown = {}
        if self._job is not None:
            current = set(self._job.progress().current) & self._wanted
            with self._lock:
                changed, self._changed = self._changed, set()
            changed = set(self._relpaths) if changed is None else changed | current | self._current
            self._current = current
            for relpath in changed:
                shown[relpath] = "%s %s" % (hashing.mark(self._job, relpath), os.path.basename(relpath))
        shown[''] = picker.status(hashing.status_parts(self._status_jobs) + (self._extra() if self._extra else []))
        return shown


def picker_status(replicas, extra=()):
    """The status of a picker of replicas (trees) that has no Marks: a label of each local one's job"""
    return picker.status(hashing.status_parts(jobs_of(replicas)) + list(extra))


def dashboard_of(replicas):
    """The dashboard (see dashboard()) of replicas (trees): the local ones' jobs, and the cloud ones"""
    dashboard(jobs_of(replicas), [replica for replica in replicas if isinstance(replica, clouddirtree.CloudDirTree)])
