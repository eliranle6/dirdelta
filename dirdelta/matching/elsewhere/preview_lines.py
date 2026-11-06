"""The lines of a missing file's preview"""
import os
import time

from dirdelta.hashes import hashing
from dirdelta.screens.hashes_screen import status as hash_status
from dirdelta.matching.elsewhere.candidates import is_same_time
from dirdelta.matching.elsewhere.constants import MAX_MATCHES, SURELY_MOVED, SURELY_RENAMED
from dirdelta.matching.elsewhere.sure import sure_match
from dirdelta.ui import picker
from dirdelta.util import text


def preview_of(relpath, src, dst_name, matcher):
    """The lines about src's file at relpath: its size, date taken and modification time, and its
    candidates, the likeliest first, of its name, then of other names, each with its dir, size,
    date taken, modification time, siblings found and contents, and which is surely the file, if
    one is; or that there are none"""
    matches = matcher.matches(relpath)
    size = src.file_size(relpath)
    # Read only for a file with candidates: they're to compare with
    date = matcher.date_taken(relpath) if matches else None
    modified = src.modified_time(relpath) if matches else None
    about = [text.format_size(size)] if size is not None else []
    if date is not None:
        about.append("taken " + date)
    lines = [picker.styled([("This one: ", 'bold'), (", ".join(about), None)])] if about else []
    if modified is not None:
        lines.append("  modified " + _format_time(modified))
    lines += _contents_lines(relpath, dst_name, matcher, matches)
    named = [match for match in matches if not match.is_other_name]
    renamed = [match for match in matches if match.is_other_name]
    sure = sure_match(matches, size, date)
    # Each part under a title, bold in its color (as an inbox's preview's)
    if named:
        lines.append(_title("Same name in %s:" % (dst_name,), 'cyan'))
        lines += _matches_lines(named, size, date, modified, sure, SURELY_MOVED)
    else:
        lines.append(picker.styled([("Same name in %s: " % (dst_name,), 'bold,cyan'), ("none", 'bold,red')]))
    if renamed:
        lines.append(_title("Same size, other name:", 'cyan'))
        lines += _matches_lines(renamed, size, date, modified, sure, SURELY_RENAMED)
    return lines


def _contents_lines(relpath, dst_name, matcher, matches):
    """A preview's lines of what's known of the file's contents by hashes (see hashing.py): its
    hash, or that it isn't hashed yet; and if no file of the other replica has its contents (of the
    ones hashed, if it isn't all hashed)"""
    if matcher.src_index is None:
        return []
    own = matcher.src_index.known(relpath)
    src_job = matcher.src_index.job()
    if not own:
        if src_job is None:
            return []
        return [picker.styled([("  contents not hashed yet (%s)" % (hash_status.status_text(src_job),), 'grey')])]
    algorithm = sorted(own)[0] if hashing.ALGORITHM not in own else hashing.ALGORITHM
    lines = [picker.styled([("  %s %s" % (algorithm.upper().replace('SHA', 'SHA-'), own[algorithm][:16]), 'grey')])]
    index = matcher._index
    if not any(match.same_contents for match in matches):
        # Of the other replica's files whose hashes by one of the file's are known
        coverage = max([index.hash_coverage(algorithm) or 0 for algorithm in own])
        if coverage >= 1:
            lines.append("  no file in %s has its contents" % (dst_name,))
        elif coverage > 0:
            lines.append("  no file in %s has its contents," % (dst_name,))
            lines.append("  of the %d%% of its files hashed%s" % (
                int(coverage * 100), " so far" if index.job() is not None else ""))
    return lines


def _title(text, color):
    """A preview's title, bold in color"""
    return picker.styled([(text, 'bold,' + color)])


def _matches_lines(matches, size, date, modified, sure, surely):
    lines = []
    for match in matches[:MAX_MATCHES]:
        dirpath, name = os.path.split(match.relpath)
        lines += ["  %s/" % (dirpath or '.',), "    %s%s" % (name, _size_note(match.size, size))]
        if match.date_taken is not None:
            lines.append("    taken %s%s" % (match.date_taken,
                                             ", the same" if match.date_taken == date else ""))
        if match.modified is not None:
            lines.append("    modified %s%s" % (_format_time(match.modified),
                                                _time_note(match.modified, modified)))
        if match.siblings_tried:
            lines.append("    with %d of %d of its dir's files" % (match.siblings_found,
                                                                   match.siblings_tried))
        if match.same_contents is not None:
            lines.append(picker.styled([("    the same contents", 'green')]) if match.same_contents else
                         picker.styled([("    other contents", 'red')]))
        if match is sure:
            lines.append(surely)
    if len(matches) > MAX_MATCHES:
        lines.append("(and %d more)" % (len(matches) - MAX_MATCHES,))
    return lines


def _format_time(timestamp):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))


def _time_note(match_modified, modified):
    """Whether a match's modification time is the same as the file's, or newer, or older"""
    if modified is None:
        return ""
    if is_same_time(match_modified, modified):
        return ", the same"
    return ", newer" if match_modified > modified else ", older"


files_text = text.files


def _size_note(match_size, size):
    if match_size is None:
        return ""
    if match_size == size:
        return "  %s, same size" % (text.format_size(match_size),)
    if size is not None and text.format_size(match_size) == text.format_size(size):
        # Not to look the same as this one's
        return "  %d B" % (match_size,)
    return "  " + text.format_size(match_size)
