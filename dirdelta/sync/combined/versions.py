"""A file's diff for a preview, in any tree that shows files two replicas have otherwise (the combined
tree's right column, a way's picker): its versions read, a Drive one downloaded first (up to
diffview.MAX_SIZE), and shown in a view of diffview's. Which views there are depends on where it's
shown: in the browser one column only (side by side doesn't fit a phone)."""
from dirdelta.sync.combined import diffview
from dirdelta.ui import frontend
from dirdelta.ui import opening
from dirdelta.ui import picker

# Ctrl-T: the next view, its hint (for the keys' help)
KEY_HINT = (diffview.KEY_NAME, "show the changes, or either whole version")


def views():
    """The views Ctrl-T goes through, the first one shown first"""
    if frontend.current is not None:
        return (diffview.UNIFIED, diffview.VERSION_A, diffview.VERSION_B)
    return (diffview.SIDE_BY_SIDE, diffview.UNIFIED, diffview.VERSION_A, diffview.VERSION_B)


def next_view(view):
    """The view after view (the first, if view is None or isn't one here)"""
    shown = views()
    return shown[(shown.index(view) + 1) % len(shown)] if view in shown else shown[0]


def width():
    """How wide the diff's lines may be: the terminal's preview column, or in the browser, any (it wraps)"""
    return 200 if frontend.current is not None else diffview.column_width()


def lines(replicas, relpath, names, view):
    """The preview's lines of relpath's diff, after a blank line and their title: of its versions in the
    two replicas (names: theirs), in view (None: the first); or, with one replica, its contents. Reads
    them, downloading a Drive one (on this thread): or says why it can't."""
    view = view if view in views() else views()[0]
    if len(replicas) == 2:
        title = picker.styled([("Diff, %s" % (diffview.view_name(view, names[0], names[1]),), 'bold'),
                               ("  (%s: the changes, or either whole version)" % (diffview.KEY_NAME,), 'grey')])
    else:
        title = picker.styled([("Its contents", 'bold')])
    versions = []
    for replica in replicas:
        try:
            path = opening.Opener(replica).local_path(relpath, diffview.MAX_SIZE)
        except OSError as error:
            return ["", title, "  Couldn't get a version of it: %s" % (error,)]
        versions.append(diffview.read_lines(path) if path is not None else None)
    if None in versions:
        return ["", title, "  Not text, or bigger than 1 MB"]
    if len(versions) == 1:
        return ["", title] + versions[0][:diffview.MAX_LINES]
    if versions[0] == versions[1]:
        return ["", title, "  Their lines are the same (they differ only in their line ends or encoding)"]
    return ["", title] + diffview.lines_of(view, versions[0], versions[1], names[0], names[1], width())
