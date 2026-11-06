"""What's shown of the jobs: each file's tag, and how far each job got"""
from dirdelta.hashes.hashing.registry import jobs
from dirdelta.hashes.hashing.states import DONE, NOT_SCANNED, SCANNING
from dirdelta.known import replicanames
from dirdelta.util import text


# What a file is shown as in a picker, after its name (a search, e.g. /not hashed, finds them):
# hashed, being hashed now, not yet, or couldn't be (unreadable, or changing while read)
HASHED_TAG = "[\u25cf hashed]"
HASHING_TAG = "[\u25d0 hashing now]"
NOT_HASHED_TAG = "[\u25cb not hashed yet]"
FAILED_TAG = "[\u2715 couldn't be hashed]"
# Each one's style (see picker.styled()): hashing in orange, as its status label
TAG_STYLES = {HASHED_TAG: 'green', HASHING_TAG: 'orange', NOT_HASHED_TAG: 'grey', FAILED_TAG: 'red'}


def tag(job, relpath):
    """The tag of the job's file at relpath (see HASHED_TAG)"""
    if job.hash_of(relpath) is not None:
        return HASHED_TAG
    if job.is_being_hashed(relpath):
        return HASHING_TAG
    return FAILED_TAG if job.is_failed(relpath) else NOT_HASHED_TAG


def percent(progress):
    """How much of the job is done, in % of its files' bytes (0-100, 100 only when it's all done);
    of its files, when they're all empty"""
    if progress.state == DONE:
        return 100
    if progress.size:
        done = progress.size_done * 100 // progress.size
    elif progress.nr_files:
        done = progress.nr_done * 100 // progress.nr_files
    else:
        done = 0
    return min(done, 99)


def color(progress):
    """The color of a job's status by how far it got: red, orange, yellow, then green once done"""
    if progress.state == DONE:
        return 'green'
    done = percent(progress)
    return 'red' if done < 34 else 'orange' if done < 67 else 'yellow'


def status_text(job, progress=None, name=None):
    """A job's status, short, for a picker's status bar: e.g. 'photos: 63% hashed (1,204/1,911, paused)',
    the percentage by size, and how many files of how many; name: the replica's name there (default: its
    dir's name)"""
    progress = progress or job.progress()
    name = name or job.name()
    if progress.state in (NOT_SCANNED, SCANNING):
        return "%s: listing its files..." % (name,)
    count = "{:,}/{:,}".format(progress.nr_done, progress.nr_files)
    if progress.state == DONE:
        return "%s: 100%% hashed \u2713 (%s)" % (name, count)
    if not progress.is_started:
        count += ", paused" if progress.is_paused else ", not hashing"
    return "%s: %d%% hashed (%s)" % (name, percent(progress), count)


def active_jobs():
    """The jobs hashing now, or paused, with files left: what every menu's status bar says"""
    found = []
    for job_ in jobs():
        progress = job_.progress()
        if progress.state != DONE and (progress.is_started or progress.is_paused):
            found.append(job_)
    return found


def status_parts(jobs):
    """[(text, color)] of the jobs' statuses, for picker.segments(), each by its replica's short name
    (one that tells it from the others, see replicanames.short_names())"""
    names = replicanames.short_names([job.root for job in jobs])
    parts = []
    for job in jobs:
        progress = job.progress()
        parts.append((status_text(job, progress, names[job.root]), color(progress)))
    return parts


def bar(progress, width=20):
    """A bar of how far a job got: [██████░░░░░░░░░░░░░░]"""
    filled = width * percent(progress) // 100
    return '[%s%s]' % ('█' * filled, '░' * (width - filled))


format_duration = text.format_duration


def time_left(progress):
    """How long the rest takes at its speed, or None if that isn't known"""
    if not progress.rate:
        return None
    return (progress.size - progress.size_done) / progress.rate
