"""d in the combined tree: the selected file's diff, A's version against B's (a file only one has:
against nothing), in less over the screen, if they're text"""
import os
import subprocess

from dirdelta.sync.combined import plan as plans
from dirdelta.ui import messages
from dirdelta.ui import opening
from dirdelta.util import dryrun
from dirdelta.util import text

KEY = 'd'
# The biggest file it's done for (a Drive one is downloaded first)
MAX_SIZE = 10 * 1024 * 1024
# How much of a file says whether it's text: no NUL bytes, and few control characters
SAMPLE_SIZE = 8192
MAX_CONTROL_SHARE = 0.05
# The control characters text has
TEXT_CONTROLS = set(b'\t\n\r\f\b\x1b')


def is_text(path):
    """Whether the file at path looks like text (any encoding but UTF-16's and the like)"""
    with open(path, 'rb') as f:
        sample = f.read(SAMPLE_SIZE)
    if b'\0' in sample:
        return False
    controls = sum(1 for byte in sample if byte < 32 and byte not in TEXT_CONTROLS)
    return controls <= MAX_CONTROL_SHARE * len(sample)


def diff_command(path_a, path_b, label_a, label_b):
    """diff's command line: unified, colored, labelled by the replicas' names (None: no file there)"""
    return (['diff', '-u', '--color=always', '--label', label_a, '--label', label_b] +
            [path_a or os.devnull, path_b or os.devnull])


def show(sync, relpath):
    """Show the file's diff (sync: a CombinedSync), or say why it can't be"""
    title = "Diff of %s" % (relpath,)
    group = sync.grouped.get(relpath)
    if group is None:
        messages.show(title, ["Select a file (not a dir) to see what differs in it."], dryrun.label())
        return
    if group == plans.MOVED:
        messages.show(title, ["It's the same contents in both (moved): nothing differs."], dryrun.label())
        return
    paths = []
    for replica, has_it in ((sync.replica_a, group != plans.ONLY_B), (sync.replica_b, group != plans.ONLY_A)):
        if not has_it:
            paths.append(None)
            continue
        messages.print_line("Getting %s's version..." % (sync.name_a if replica is sync.replica_a else sync.name_b,))
        try:
            path = opening.Opener(replica).local_path(relpath, MAX_SIZE)
        except OSError as error:
            messages.show(title, ["Couldn't download it: %s" % (error,)], dryrun.label(), 'red')
            return
        if path is None:
            messages.show(title, ["It's too big to diff (more than %s), or can't be downloaded." %
                                  (text.format_size(MAX_SIZE),)], dryrun.label())
            return
        paths.append(path)
    try:
        if not all(is_text(path) for path in paths if path):
            messages.show(title, ["It isn't text: there's no diff to show."], dryrun.label())
            return
        diff = subprocess.run(diff_command(paths[0], paths[1], "%s/%s" % (sync.name_a, relpath),
                                           "%s/%s" % (sync.name_b, relpath)),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as error:
        messages.show(title, ["Couldn't diff it: %s" % (error,)], dryrun.label(), 'red')
        return
    if diff.returncode > 1:
        messages.show(title, ["diff failed: %s" % (diff.stderr.decode(errors='replace').strip(),)], dryrun.label(), 'red')
        return
    if not diff.stdout:
        messages.show(title, ["Their contents are the same."], dryrun.label())
        return
    try:
        # q goes back to the tree
        subprocess.run(['less', '-R', '-c'], input=diff.stdout)
    except OSError:
        messages.show(title, diff.stdout.decode(errors='replace').splitlines(), dryrun.label())
