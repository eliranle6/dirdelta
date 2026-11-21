"""A sync's one screen of its differences, seen two ways chosen apart (SyncMenu's sync_view()): which files (SCOPES: all
of them, only in A, only in B, the ones that differ, the moved ones) and how they're chosen (MODES: PLAN, each marked
⇒ ⇐ then done in one go, the combined tree; ACT, checked then acted on at once, a files tree). Each of the trees has
SWITCH_KEY, which ends it asking for another view: the one the web page asked for with it (request(), see web/api.py),
or else (the terminal) the other mode."""
from dirdelta.ui import frontend

# The files shown (the combined tree's groups, and all of them) and the ways they're chosen
ALL, ONLY_A, ONLY_B, DIFFER, MOVED = 'all', 'only-a', 'only-b', 'differ', 'moved'
SCOPES = (ALL, ONLY_A, ONLY_B, DIFFER, MOVED)
PLAN, ACT = 'plan', 'act'
MODES = (PLAN, ACT)

# The key that ends a sync's tree asking for another view (none of treepicker's, nor the trees' own)
SWITCH_KEY, SWITCH_KEY_NAME = '\x02', 'Ctrl-B'


def requested(scope, mode):
    """The view asked for with SWITCH_KEY: (scope, mode), the web page's (see web/api.py), else (the terminal) scope
    in the other mode"""
    asked = getattr(frontend.current, 'view_request', None) if frontend.current is not None else None
    if frontend.current is not None:
        frontend.current.view_request = None
    if asked and asked.get('scope') in SCOPES and asked.get('mode') in MODES:
        return asked['scope'], asked['mode']
    return scope, ACT if mode == PLAN else PLAN


def show(scope, mode, scopes):
    """Tell the web page the view shown (its scope and mode) and the scopes there are: [(scope, title, count)]"""
    if frontend.current is not None:
        frontend.current.sync_view = {'scope': scope, 'mode': mode,
                                      'scopes': [{'scope': one, 'title': title, 'count': count} for one, title, count in scopes]}
