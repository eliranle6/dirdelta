"""Labeling replicas (see replicanames.py), e.g. 'laptop' or 'blue WD ext. disk'."""
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicanames
from dirdelta import replicas

NOTHING = "Nothing: go back"


def _what(path):
    """What the label of the replica at path is of"""
    if paths.is_cloud_path(path):
        return "%s (%s)" % (path, replicanames.disk_name(path))
    return "the disk %s (which has %s)" % (replicanames.disk_name(path), path)


def run(known, replica_paths):
    """Let the user label the replicas at replica_paths, or remove their labels, until they go back.
    known: a replicas.Replicas, saved when they change"""
    while True:
        forms = {}
        for path in replica_paths:
            key = replicanames.label_key(path)
            current = known.labels.get(key)
            # Two replicas on one disk have one label
            if key not in [form[1] for form in forms.values()]:
                forms["Label %s%s" % (_what(path), ": now '%s'" % (current,) if current else "")] = (path, key, False)
                if current:
                    forms["Remove the label '%s' of %s" % (current, _what(path))] = (path, key, True)
        answer = picker.pick_option([NOTHING] + list(forms),
                                    header="A label says which replica is which, e.g. 'laptop' or 'blue WD ext. disk'.\n"
                                           "A disk's label is of all the replicas on it.",
                                    title="Labels")
        if answer not in forms:
            return
        path, key, is_removed = forms[answer]
        if is_removed:
            known.set_label(key, None)
        else:
            name = messages.ask("A label of %s" % (_what(path),), ["Its label (empty, or Ctrl-C, goes back):"], "> ",
                                known.labels.get(key, ''), dryrun.label())
            if name is None:
                continue
            known.set_label(key, name)
        replicas.save(known)
