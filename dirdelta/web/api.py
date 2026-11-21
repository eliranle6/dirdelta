"""The web version's API for the session's screens (routes()): what the page polls for (what's shown,
and what changed since it last asked) and what it does there (the picker's moves and keys, a messages
screen's Continue or answer, Stop, and starting dirdelta's start menu)"""
from dirdelta.known import replicanames
from dirdelta.known import replicas as known_replicas
from dirdelta.trees import paths
from dirdelta.sync.view import SWITCH_KEY
from dirdelta.util import dryrun
from dirdelta.web import server
from dirdelta.web.picker import PickerScreen

# The biggest picture a grid asks for (a side, in pixels): one shown whole
MAX_PICTURE_SIZE = 1600
# The mode's labels (dryrun.label()'s): a screen's is shown as the mode is now, which may have been switched since
MODE_LABELS = ('DRY RUN', 'LIVE')

# How long a poll waits for a change, in seconds (under what a phone's browser lets a request take)
POLL_WAIT = 20
# How long it waits for the next screen while the flow's between two (one closed, the next coming): rather than
# say there's none, and the page ask again (a round trip, slow on a phone's Wi-Fi)
NEXT_SCREEN_WAIT = 0.4


def routes(session, start_flow):
    """{(method, path): handler(query, body) -> JSON}: start_flow(body) runs the flow asked for (see
    daemon.flow(): the start menu, a pair's sync, or an inbox's sort)"""
    def state(query, body):
        since = int(query.get('since', 0))
        if since > 0:
            # (A page's first ask is answered at once: nothing may change for a while)
            session.wait(since, POLL_WAIT)
            session.wait_for_screen(NEXT_SCREEN_WAIT)
        screen = session.screen()
        found = {'version': session.version, 'running': session.is_running, 'tab': session.tab,
                 'log': [list(line) for line in session.log], 'screen': None}
        if screen is not None:
            is_new = str(screen.id) != query.get('screen')
            found['screen'] = dict(screen.meta(), **screen.state(0 if is_new else since))
            found['screen']['labels'] = with_mode_now(found['screen'].get('labels') or [])
            if session.replicas:
                found['screen']['replicas'] = replicas_shown(session.replicas)
            # (Only a tree that can switch the view: a sync's plan, its sides' or both sides' files, not a folder chooser)
            if isinstance(screen, PickerScreen) and session.sync_view and SWITCH_KEY in screen.spec.expect:
                found['screen']['syncView'] = session.sync_view
            if is_new and isinstance(screen, PickerScreen):
                found['screen']['items'] = screen.items.listed()
        return found

    def preview(query, body):
        screen = session.screen(int(query.get('screen', 0)))
        return screen.preview(query.get('path', '')) if isinstance(screen, PickerScreen) else {}

    def picture(query, body):
        """A file's picture, a JPEG (a folder's photos' grid), at most size pixels a side"""
        screen = session.screen(int(query.get('screen', 0)))
        size = max(32, min(MAX_PICTURE_SIZE, int(query.get('size', 240))))
        data = screen.picture(query.get('path', ''), size) if isinstance(screen, PickerScreen) else None
        return server.Reply(data, 'image/jpeg', is_kept=True) if data else server.Reply(b'', 'text/plain', 404)

    def children(query, body):
        screen = session.screen(int(query.get('screen', 0)))
        return screen.items.children(query.get('path', '')) if isinstance(screen, PickerScreen) else []

    def act(query, body):
        screen = session.screen(body.get('screen'))
        action = body.get('action')
        if action == 'stop':
            session.stop()
        elif screen is None:
            return {'ok': False}
        elif screen.kind == 'messages':
            screen.answer(body.get('text'))
        elif screen.kind == 'merge':
            screen.act(body.get('merge') or {})
        else:
            # (A sync's switch: the view asked for with it, which the flow reads as the key ends its tree, view.py)
            if action == 'press' and isinstance(body.get('view'), dict):
                session.view_request = body['view']
            _act_on_picker(screen, action, body)
        return {'ok': True}

    def start(query, body):
        # (What it's about: a sync (or the start menu) is the replicas', a sort the inboxes')
        return {'ok': session.start(lambda: start_flow(body), 'inboxes' if body.get('kind') == 'sort' else 'replicas',
                                   dict(body))}

    return {('GET', '/api/state'): state, ('GET', '/api/preview'): preview, ('GET', '/api/children'): children,
            ('GET', '/api/picture'): picture,
            ('POST', '/api/act'): act, ('POST', '/api/start'): start}


def _act_on_picker(screen, action, body):
    if action == 'select':
        screen.select(body['path'])
    elif action == 'pick':
        screen.pick(body['paths'], bool(body.get('on', True)))
    elif action == 'state':
        screen.items.set_state(body['paths'], body['name'])
    elif action == 'press':
        screen.press(body['key'])
    elif action == 'enter':
        screen.enter(side=bool(body.get('side')), side_key=body.get('key', ''))
    elif action == 'sideSelect':
        screen.side_selected = body['path']
    elif action == 'quit':
        screen.quit()


def with_mode_now(labels):
    """A screen's labels, the mode's (DRY RUN or LIVE) as it is now: the top bar's switch may have changed it
    since the screen was opened"""
    return [list(dryrun.label()) if label[0] in MODE_LABELS else list(label) for label in labels]


def replicas_shown(pair):
    """The two replicas a screen is about ([(path, name)], see frontend.show_replicas()), as the page shows
    them: [{'path', 'name', 'drive', 'look': how the user has it shown (its color and icon, see replicas.looks)}]"""
    try:
        looks = known_replicas.load().looks
    except known_replicas.ReplicasError:
        looks = {}
    # (Each by its name as it is now, not as the flow had it when it started: a replica named meanwhile is shown so)
    names = replicanames.short_names([path for path, _ in pair])
    return [{'path': path, 'name': names[path], 'drive': paths.is_cloud_path(path),
             'look': looks.get(replicanames.label_key(path)) or {}} for path, _ in pair]
