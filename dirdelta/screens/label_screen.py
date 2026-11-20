"""Naming replicas (see replicanames.py, which keeps a name as a label), e.g. 'desktop' or 'blue external disk'."""
from dirdelta.util import dryrun
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.known import replicanames
from dirdelta.known import replicas

NOTHING = "Nothing: go back"


def _what(path):
    """The replica at path, as it's said here"""
    return "%s (%s)" % (path, replicanames.disk_name(path))


def run(known, replica_paths):
    """Let the user label the replicas at replica_paths, or remove their labels, until they go back.
    known: a replicas.Replicas, saved when they change"""
    while True:
        options = [NOTHING]
        for path in replica_paths:
            key = replicanames.label_key(path)
            current = known.labels.get(key)
            options.append(picker.Option((path, key, False), "Name %s%s" % (
                _what(path), ": now '%s'" % (current,) if current else "")))
            if current:
                options.append(picker.Option((path, key, True), "Remove the name '%s' of %s" % (current, _what(path))))
        answer = picker.pick_option(options,
                                    header="A name says which replica is which, e.g. 'desktop' or 'blue external disk'.",
                                    title="Names")
        if not isinstance(answer, tuple):
            return
        path, key, is_removed = answer
        if is_removed:
            known.set_label(key, None)
        else:
            name = messages.ask("The name of %s" % (_what(path),), ["Its name (empty, or Ctrl-C, goes back):"], "> ",
                                known.labels.get(key, ''), dryrun.label())
            if name is None:
                continue
            known.set_label(key, name)
        replicas.save(known)
