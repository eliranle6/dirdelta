"""dirdelta's daemon (run(): dirdelta --serve): the web version on the local network, at the port and
with the key kept in access.WEB_FILE, its pickers and messages in the browser (ui/frontend.py), and the
watcher, which emails the user a link when a phone is plugged in (to import its photos) or a known
replica's drive is mounted (to sync it)"""
import sys
import threading

from dirdelta.known import users
from dirdelta.sharing import link as sharing
from dirdelta.ui import frontend
from dirdelta.util import dryrun
from dirdelta.web import access, adding, api, home, importing, server
from dirdelta.web.session import Session
from dirdelta.web.watcher import PHONE, Watcher

# Every address of the computer: the local network's, and localhost
HOST = '0.0.0.0'


def run(port=None):
    found = access.settings()
    port = port or found['port']
    key = found['key']
    session = Session()
    frontend.current = session
    routes = dict(api.routes(session, flow))
    routes.update(importing.routes())
    routes.update(home.routes(session))
    routes.update(adding.routes())
    web_server = server.serve(routes, key, HOST, port)
    watcher = Watcher(lambda kind, name, path, whose: _say(kind, name, key, port, whose))
    watcher.start()
    _out("dirdelta's web version (%s): %s\n" % (dryrun.label()[0], access.link(key, port)))
    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        session.cancel()
        web_server.server_close()


def flow(body):
    """Run the flow body asks for: {'kind': 'pair', 'a', 'b'} a sync, {'kind': 'sort', 'inbox', 'root'}
    an inbox's sort, else the start menu"""
    from dirdelta import main
    kind = body.get('kind')
    if kind == 'pair':
        return main.run_pair(body['a'], body['b'])
    if kind == 'sort':
        return main.run_sort(body['inbox'], body['root'])
    return main.start_menu()


def _say(kind, name, key, port, whose):
    """Email each user of whose a link to what appeared (opening the page as them): a phone's import
    page, or the start menu"""
    for user in whose:
        if kind == PHONE:
            url, what = access.link(key, port, '/inboxes', u=user), "Import the photos of %s" % (name,)
        else:
            url, what = access.link(key, port, u=user), "Sync %s (it's there now)" % (name,)

        def send(user=user, url=url, what=what):
            with users.acting_as(user):
                _out("%s (%s): %s\n" % (what, user, sharing.email(url, what)))
        threading.Thread(target=send, daemon=True).start()


def _out(text):
    """Say text on the daemon's own output (its log), not the web version's (where messages go)"""
    sys.stdout.write(text)
    sys.stdout.flush()
