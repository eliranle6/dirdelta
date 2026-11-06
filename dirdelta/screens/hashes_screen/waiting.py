"""Waiting for the hashing, and whether it's all right to quit meanwhile"""
import shutil
import time

from dirdelta.hashes import hashing
from dirdelta.known import replicanames
from dirdelta.screens.hashes_screen.names import KEEP_HASHING, KEY, QUIT_ANYWAY, WAIT_INTERVAL, _files
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text


def is_ok_to_quit():
    """Whether to quit: asked if any replica is still being hashed, since it stops with dirdelta"""
    running = [job for job in hashing.jobs() if job.is_started() and job.progress().state != hashing.DONE]
    if not running:
        return True
    names = replicanames.short_names([job.root for job in running])
    lines = ["%s isn't all hashed yet." % (", ".join(names[job.root] for job in running),),
             "Hashing stops if you quit. What's hashed is kept, and it can go on next time."]
    return picker.pick_option([KEEP_HASHING, QUIT_ANYWAY], header='\n'.join(lines), title="Quit?") == QUIT_ANYWAY


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
        _files(progress.nr_files), text.format_size(progress.size_done), text.format_size(progress.size))
    if progress.rate and progress.is_started and progress.state != hashing.DONE:
        line += ", %s/s" % (text.format_size(progress.rate),)
        left = hashing.time_left(progress)
        if left is not None and progress.state != hashing.DONE:
            line += ", ~%s left" % (text.format_duration(left),)
    return line


def wait(jobs):
    """Show how far the jobs got, on a screen, until they're done, or Ctrl-C (they go on, in the
    background)"""
    names = ", ".join(job.root for job in jobs)
    with messages.progress_screen("Hashing the files of %s" % (names,), dryrun.label(), is_stoppable=False,
                                  wait=False, keys=[('Ctrl-C', 'go on (it hashes in the background)')]):
        messages.print_line("Each file is read once, and its hash kept. %s in the file pickers shows how far "
                            "it got." % (KEY,))
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
