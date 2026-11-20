"""The web version's API for the session's screens (routes()): what the page polls for (what's shown,
and what changed since it last asked) and what it does there (the picker's moves and keys, a messages
screen's Continue or answer, Stop, and starting dirdelta's start menu)"""
from dirdelta.web.picker import PickerScreen

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
            if is_new and isinstance(screen, PickerScreen):
                found['screen']['items'] = screen.items.listed()
        return found

    def preview(query, body):
        screen = session.screen(int(query.get('screen', 0)))
        return screen.preview(query.get('path', '')) if isinstance(screen, PickerScreen) else {}

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
        else:
            _act_on_picker(screen, action, body)
        return {'ok': True}

    def start(query, body):
        # (What it's about: a sync (or the start menu) is the replicas', a sort the inboxes')
        return {'ok': session.start(lambda: start_flow(body), 'inboxes' if body.get('kind') == 'sort' else 'replicas',
                                   dict(body))}

    return {('GET', '/api/state'): state, ('GET', '/api/preview'): preview, ('GET', '/api/children'): children,
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
