"""Hashing a sync's local replicas, chosen from its menu (choose()): all their files, all but the media
files, the media files too, or pausing it"""
from dirdelta.hashes import hashing
from dirdelta.known import replicanames
from dirdelta.screens.hashes_screen.names import files_text, media_files_text
from dirdelta.ui import picker
from dirdelta.util import text

# What the sync menu's option says
TITLE = "Hash the replicas' files..."
HASH_ALL = "Hash all their files, in the background"
HASH_BUT_MEDIA = "Hash all but the media files, in the background"
PAUSE = "Pause hashing"
BACK = "Back"


def choose(jobs):
    """Ask what to do with the hashing of the jobs (the local replicas', scanned) and do it: hash all their
    files, or all but the media files (images, audio, video: left out, they're matched by their names and
    sizes), in the background; or pause it"""
    names = replicanames.short_names([job.root for job in jobs])
    lines = ["Hashing finds a file by its contents, whatever its name. Media files (images, audio, video) "
             "are hashed last, being the slowest and least likely to change: left out, they're matched by "
             "their names and sizes only.", ""]
    lines += [state_line(job, names[job.root]) for job in jobs]
    is_hashing = any(job.is_started() and job.progress().state != hashing.DONE for job in jobs)
    options = [HASH_ALL, HASH_BUT_MEDIA] + ([PAUSE] if is_hashing else []) + [BACK]
    answer = picker.pick_option(options, header='\n'.join(lines), title="Hash files")
    if answer == PAUSE:
        for job in jobs:
            job.pause()
    elif answer in (HASH_ALL, HASH_BUT_MEDIA):
        for job in jobs:
            job.set_media(answer == HASH_ALL)
            job.start()


def state_line(job, name):
    """'A: 120 of 300 files hashed (hashing); 40 media files (1.2 GB) left out'"""
    progress = job.progress()
    if progress.state == hashing.DONE:
        line = "%s: all %s hashed" % (name, files_text(progress.nr_files))
    else:
        doing = "hashing" if progress.is_started else "paused" if progress.is_paused else "not started"
        line = "%s: {:,} of %s hashed (%s)".format(progress.nr_done) % (name, files_text(progress.nr_files), doing)
    if progress.nr_left_out:
        line += "; %s (%s) left out" % (media_files_text(progress.nr_left_out), text.format_size(progress.size_left_out))
    return line
