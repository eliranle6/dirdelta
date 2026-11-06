"""The replicas dashboard: each replica's files, last update and hashing"""
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.screens.hashes_screen.dashboard_actions import finish_dashboard
from dirdelta.screens.hashes_screen.dashboard_lines import jobs_by_name
from dirdelta.screens.hashes_screen.dashboard_rows import add_pair, add_replica, known_pairs
from dirdelta.screens.hashes_screen.names import INBOXES_HEADING, PAIRS_HEADING, REPLICAS_HEADING
from dirdelta.ui import picker


def dashboard(replica_trees=(), known=None, other_paths=()):
    """The replicas dashboard, until Back (or q): for each replica (of replica_trees, then of
    other_paths, replicas' paths without trees, e.g. all the known ones), its files (how many,
    their size), what's known of it (known, a replicas.Replicas, else the one saved: its log's last
    entry, when it was last synced and changed), and its hashes: a local one's hashing, if it has a
    job (a bar, files, sizes, speed, time left, the files being hashed now; pausing or resuming it,
    its files, hashed or not, and scanning it again), else how many of its files' hashes are kept;
    and how many of a cloud one's files Drive gave hashes of; and labeling it (see label_screen.py)"""
    if known is None:
        try:
            known = replicas.load()
        except replicas.ReplicasError:
            known = None
    selected = None
    # Made anew after a label changed: it's in the headings
    while True:
        selected = _show_dashboard(replica_trees, known, other_paths, selected)
        if selected is None:
            return


def _show_dashboard(replica_trees, known, other_paths, selected):
    """The dashboard, starting with selected (else the first that can be picked), until Back (returns
    None), or until a replica was labeled (returns the option, to show it anew)"""
    items = [(tree.displayname(), tree) for tree in replica_trees]
    items += [(path, None) for path in other_paths if path not in dict(items)]
    # The replicas, then the inboxes (files waiting to be sorted, not replicas), each under a heading
    inboxes = {inbox for inbox, _ in known.sorts} if known is not None else set()
    roots = {root for _, root in known.sorts} if known is not None else set()
    items = ([item for item in items if item[0] not in inboxes or item[0] in roots] +
             [item for item in items if item[0] in inboxes and item[0] not in roots])
    inbox_names = {name for name, _ in items if name in inboxes and name not in roots}
    jobs = list(jobs_by_name(items).values())
    names = replicanames.short_names([name for name, _ in items])
    options, shown = [], {}
    sections = [(REPLICAS_HEADING, [item for item in items if item[0] not in inbox_names]),
                (INBOXES_HEADING, [item for item in items if item[0] in inbox_names])]
    def add_blank():
        options.append(picker.BLANK)
    # What's synced to what first, under its heading, if any pair is known
    pairs = known_pairs(known)
    if pairs:
        options.append(PAIRS_HEADING)
        shown[PAIRS_HEADING] = picker.Skipped(picker.styled([(PAIRS_HEADING, 'bold,green')]))
        for number, (path_a, path_b) in enumerate(pairs):
            if number:
                add_blank()
            add_pair(path_a, path_b, options, shown, known)
    # A heading for each only when there are both (or pairs before them)
    has_headings = all(section for _, section in sections) or bool(pairs)
    for heading, section in sections:
        if section and has_headings:
            if options:
                add_blank()
            options.append(heading)
            shown[heading] = picker.Skipped(picker.styled([(heading, 'bold,blue' if heading == REPLICAS_HEADING else 'bold,magenta')]))
        for item in section:
            if options and options[-1] != heading:
                # Each replica apart
                add_blank()
            add_replica(item, options, shown, known, names)
    return finish_dashboard(items, options, shown, names, jobs, known, selected)
