"""Whether to hash a replica's files when it's opened"""
from dirdelta.hashes import hashing
from dirdelta.known import replicanames
from dirdelta.screens.hashes_screen.names import (HASH_AND_WAIT,
    HASH_IN_BACKGROUND,
    NOTHING,
    NOT_NOW,
    _files,
    is_local)
from dirdelta.screens.hashes_screen.waiting import wait
from dirdelta.ui import messages
from dirdelta.ui import picker


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
    names = replicanames.short_names([job.root for job, _ in left])
    lines = ["Hash unhashed files?", ""]
    lines += ["%s unhashed in %s." % (_files(progress.nr_files - progress.nr_done), names[job.root])
              for job, progress in left]
    lines.append("It helps compare files, but may slow down the machine.")
    answer = picker.pick_option([NOTHING, NOT_NOW, HASH_AND_WAIT, HASH_IN_BACKGROUND],
                                header='\n'.join(lines), title="Hash files?")
    if answer in (None, NOTHING):
        return False
    if answer in (HASH_AND_WAIT, HASH_IN_BACKGROUND):
        for job, _ in left:
            job.start()
    if answer == HASH_AND_WAIT:
        wait([job for job, _ in left])
    return True


def scan_with_listing(job, listing):
    """Have the job look for changes in its replica with what the replica's sidetree.Listing lists next,
    if it goes as deep as the job does (else the job lists them itself)"""
    listing.invalidate(job.scan_in_background if job.max_depth == listing.max_depth else lambda files: job.scan_in_background())


def hashing_status():
    """What a menu's status bar says of all the jobs (for pick_option's shown_as)"""
    return {'': picker.segments(hashing.status_parts(hashing.jobs()))}
