"""Choosing, as a sort starts, which of the sorted tree's other replicas get its new files too: none
unless the user picks them"""
import os

from dirdelta.inbox.constants import LABEL
from dirdelta.known import replicanames
from dirdelta.screens import replica_choices
from dirdelta.trees import paths
from dirdelta.ui import picker


GO_ON = 'go on'
ADD = 'add'
GO_ON_NONE = "Go on, copying into no other replica"
GO_ON_PICKED = "Go on, copying into the %d picked too"
ADD_LABEL = "Another replica of it (choose a dir)..."
PICKED_MARK = "[x] "
NOT_PICKED_MARK = "[ ] "


def choose(known_replicas, inbox_path, root_path):
    """Let the user pick which replicas of the sorted tree at root_path (known_replicas' followers_of()
    it, and any other they choose) get copies of the files the sort puts into it, none picked at
    first. Returns their paths ([] for none: at once, with none known), or None if the user quit; the
    ones picked are remembered in known_replicas (not saved)."""
    found = [path for path in known_replicas.followers_of(root_path)
             if paths.normalized(path) != paths.normalized(inbox_path)]
    if not found:
        return []
    picked, selected = [], GO_ON
    while True:
        options = [picker.Option(GO_ON, GO_ON_PICKED % (len(picked),) if picked else GO_ON_NONE), picker.BLANK]
        for path in found:
            why_not = cant_follow(root_path, path)
            label = (PICKED_MARK if path in picked else NOT_PICKED_MARK) + path
            options.append(picker.Option(('toggle', path), label,
                                         picker.Disabled("%s (%s)" % (label, why_not)) if why_not else None))
        options += [picker.BLANK, picker.Option(ADD, ADD_LABEL)]
        header = ("Also copy what this sort moves or copies into %s into other replicas of it? Enter picks one "
                  "(or unpicks it); none are, unless picked. A file there already is left as it is." %
                  (replicanames.short_names([root_path])[root_path],))
        chosen = picker.pick_option(options, header=header, selected=selected, label=LABEL,
                                    title="Other replicas of the sorted tree")
        if chosen is None:
            return None
        if chosen == GO_ON:
            known_replicas.record_followers(root_path, picked)
            return [path for path in found if path in picked]
        if chosen == ADD:
            path = replica_choices.choose_replica("another replica of %s" % (root_path,))
            if path is None:
                continue
            path = paths.normalized(path)
            if path in (paths.normalized(root_path), paths.normalized(inbox_path)):
                continue
            if path not in found:
                found.append(path)
            if not cant_follow(root_path, path) and path not in picked:
                picked.append(path)
            selected = ('toggle', path)
            continue
        path = chosen[1]
        picked = [old for old in picked if old != path] if path in picked else picked + [path]
        selected = chosen


def cant_follow(root_path, path):
    """Why the replica at path can't get copies of the sorted tree's files (at root_path), or None if
    it can: both in Drive (no copies within it), or a local dir that isn't there (not mounted) or is
    read-only"""
    if paths.is_cloud_path(path):
        return "both in Google Drive: no copies within it" if paths.is_cloud_path(root_path) else None
    if not os.path.isdir(path):
        return "not there: not mounted?"
    if not os.access(path, os.W_OK):
        return "read-only"
    return None
