"""Whether to hash a replica's files when it's opened"""
from dirdelta.hashes import hashing
from dirdelta.screens.hashes_screen import status as hash_status
from dirdelta.known import replicanames
from dirdelta.screens.hashes_screen.names import (HASH_AND_WAIT, HASH_BUT_MEDIA_AND_WAIT,
                                                  HASH_BUT_MEDIA_IN_BACKGROUND, HASH_IN_BACKGROUND, NOTHING,
                                                  NOT_NOW, KEY, files_text, is_local,
                                                  media_files_text)
from dirdelta.screens.hashes_screen.waiting import wait
from dirdelta.ui import messages

# Why leaving the media files out can't be chosen
NO_MEDIA_LEFT = "no photos or videos left to hash"
from dirdelta.ui import picker
from dirdelta.util import text


def prepare(replicas):
    """The jobs of the local replicas (of replicas, trees), each scanned (its files listed, and which
    are hashed found), once"""
    jobs = []
    for replica in replicas:
        if not is_local(replica):
            continue
        job = hashing.job(replica.fullpath(), replica.max_depth)
        if job.progress().state == hashing.NOT_SCANNED:
            if replica.file_stamps is not None and job.max_depth == replica.max_depth:
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
    hashed): nothing (going back), not now, now, waiting for it (recommended), or in the background;
    and when there are media files (images, audio, video) and others left, the same without the
    media, which are the least likely to have changed and the slowest to hash (they're hashed last
    anyway). The ones all hashed are started (so files that come later are hashed too). Returns
    whether to go on (False: the user chose nothing, or quit)."""
    left = []
    for job in jobs:
        progress = job.progress()
        if progress.state == hashing.DONE:
            job.start()
        elif not job.is_started() and progress.state != hashing.NOT_SCANNED:
            left.append((job, progress))
    if not left:
        return True
    names = replicanames.short_names([job.root for job, _ in left])
    lines = ["Hash the files first? It reads their contents, to find a file however it was moved or renamed.", ""]
    has_media = False
    for job, progress in left:
        others, media_files = job.left()
        if media_files.nr_files:
            # (Leaving them out is a choice even with no other file left: it hashes the ones that come later)
            has_media = True
            lines.append("%s unhashed in %s (%s), and %s (%s)." % (
                files_text(others.nr_files) if others.nr_files else "No other file", names[job.root],
                text.format_size(others.size), media_files_text(media_files.nr_files), text.format_size(media_files.size)))
        else:
            lines.append("%s unhashed in %s." % (files_text(progress.nr_files - progress.nr_done), names[job.root]))
    if has_media:
        lines.append("Photos, audio and videos are the slowest: left out, they're matched by name and size.")
    # (The one that keeps going first, and chosen; going back is Back, q. Without media files left, leaving them
    # out is shown, off, saying why)
    def but_media(option):
        return option if has_media else picker.Option(option, option, picker.Disabled("%s (%s)" % (option, NO_MEDIA_LEFT)))
    options = [HASH_IN_BACKGROUND, but_media(HASH_BUT_MEDIA_IN_BACKGROUND), HASH_AND_WAIT,
               but_media(HASH_BUT_MEDIA_AND_WAIT), NOT_NOW]
    answer = picker.pick_option(options, header='\n'.join(lines), title="Hash files?", selected=HASH_IN_BACKGROUND)
    if answer in (None, NOTHING):
        return False
    if answer != NOT_NOW:
        for job, _ in left:
            job.set_media(answer in (HASH_AND_WAIT, HASH_IN_BACKGROUND))
            job.start()
    if answer in (HASH_AND_WAIT, HASH_BUT_MEDIA_AND_WAIT):
        wait([job for job, _ in left])
    return True


def scan_with_listing(job, listing):
    """Have the job look for changes in its replica with what the replica's sidetree.Listing lists next,
    if it goes as deep as the job does (else the job lists them itself)"""
    listing.invalidate(job.scan_in_background if job.max_depth == listing.max_depth else lambda files: job.scan_in_background())


def hashing_status():
    """What a menu's status bar says of all the jobs (for pick_option's shown_as)"""
    return {'': picker.segments(hash_status.status_parts(hashing.jobs()))}
