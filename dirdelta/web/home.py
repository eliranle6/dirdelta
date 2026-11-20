"""The web version's dashboard and Replicas page's API (routes()): the user's replicas (each one's disk,
whether it's there, its hashing, its log's last entry, when it was last synced) and every two of them,
a pair to sync (as a flow, see daemon.flow()), their inboxes, what's running; hashing a replica, or
pausing it; and the users (users.py)"""
import os

from dirdelta.drive import driveapi
from dirdelta.drive import freshening
from dirdelta.hashes import hashcache
from dirdelta.hashes import hashing
from dirdelta.known import mounts
from dirdelta.known import replicainfo
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.known import settings
from dirdelta.known import users
from dirdelta.matching import syncstate
from dirdelta.phoneimport import sources
from dirdelta.trees import paths
from dirdelta.util import dryrun
from dirdelta.web import importing
from dirdelta.web import naming
from dirdelta.web.importing import checks


def _device(path):
    """What the local path is on, for its icon: 'laptop' (the system's own disk) or 'disk' (another)"""
    mount = mounts.current_mount(path)
    return 'laptop' if mount is None or mount.target in ('/', '/home') else 'disk'


def _when(stamp):
    """A datetime as 'YYYY-MM-DD HH:MM', or None"""
    return stamp.strftime('%Y-%m-%d %H:%M') if stamp else None


def replica_info(path, known_replicas):
    """What the dashboard says of the replica at path: its name, kind, what it's on (its icon), whether it's there, its hashing (a local one's), when its list was
    read (a Drive one's), its log's last entry, and when it was last synced and changed"""
    is_cloud = paths.is_cloud_path(path)
    found = {'path': path, 'name': naming.own_name(path), 'place': naming.place(path), 'fullName': naming.name(path),
             'kind': 'drive' if is_cloud else 'local', 'disk': replicanames.disk_name(path),
             'device': 'drive' if is_cloud else _device(path)}
    if is_cloud:
        found['there'], found['why'] = True, ''
        found['reading'] = next((one for one in freshening.reading() if one['path'] == path), None)
        found['listedAt'] = _when(replicainfo.cache_time(path))
    else:
        unmounted = mounts.unmounted(path)
        found['there'] = unmounted is None and os.path.isdir(path)
        found['why'] = ("its disk isn't mounted" if unmounted is not None else
                        "not there" if not found['there'] else '')
        found['hashing'] = checks.hash_state(path)
        found['hashesKept'] = hashcache.count_under(path) if found['there'] else 0
    info = known_replicas.info_at(path) or {}
    found.update(lastEntry=info.get('last_entry'), seen=info.get('seen'), changed=info.get('changed'))
    return found


def _title(screen):
    """What the screen shown is called (its breadcrumbs' last part), or ''"""
    if screen is None:
        return ''
    meta = screen.meta()
    title = meta.get('title') or meta.get('crumbs') or ''
    if isinstance(title, str) and title:
        return title.replace('\x01', ' ').split(' > ')[-1].strip()
    # (A picker's: its question, its header's first line, without its styles' marks)
    header = meta.get('header') or ''
    return header.split('\n', 1)[0].replace('\x01', ' ').replace('\x02', '').strip() if isinstance(header, str) else ''


def _is_waiting(screen):
    """Whether what's shown waits for the user: a picker, or a messages screen's Continue or question"""
    if screen is None:
        return False
    return screen.kind == 'picker' or bool(getattr(screen, 'waiting', False) or getattr(screen, 'asking', False))


def pair_info(path_a, path_b, names, known_replicas):
    """What the dashboard says of a pair: its sync state, as the terminal's dashboard does (syncstate:
    in sync, one ahead, branched or not known; its mark and color, grey if a replica changed since;
    what it is in words, by the replicas' short names)"""
    name_a, name_b = names.get(path_a, path_a), names.get(path_b, path_b)
    state = syncstate.of(known_replicas, path_a, path_b)
    mark, color = syncstate.mark(state)
    return {'a': path_a, 'b': path_b, 'nameA': name_a, 'nameB': name_b,
            'favorite': (path_a, path_b) in known_replicas.favorites, 'compared': known_replicas.comparison(path_a, path_b),
            'state': {'kind': state.kind, 'mark': mark, 'color': color, 'when': state.when,
                      'text': syncstate.describe(state._replace(changed=[names.get(path, path) for path in state.changed]),
                                                 name_a, name_b)},
            'synced': _synced(known_replicas.comparison(path_a, path_b)),
            'changedSince': [names.get(path, path) for path in state.changed]}


def _synced(comparison):
    """How much of the pair was in step when it was last compared: {'onlyA', 'onlyB', 'totalA', 'totalB',
    'share': the files both had, of all either had (0-1; None if the totals weren't noted then)}, or None"""
    if comparison is None:
        return None
    (only_a, only_b), total = comparison['only'], comparison.get('total')
    found = {'onlyA': only_a, 'onlyB': only_b, 'totalA': None, 'totalB': None, 'share': None}
    if total:
        both, either = total[0] - only_a, total[0] + only_b
        found.update(totalA=total[0], totalB=total[1], share=both / either if either else 1.0)
    return found


def routes(session):
    def home(query, body):
        known_replicas = replicas.load()
        all_paths = known_replicas.replica_paths()
        # (Drive's lists of the user's replicas and inboxes over a day old read again, in the background)
        freshening.refresh_stale(all_paths + known_replicas.inbox_paths())
        screen = session.screen()
        names = {path: naming.name(path) for path in all_paths}
        return {'label': list(dryrun.label()),
                'running': {'title': _title(screen), 'waiting': _is_waiting(screen), 'user': session.user, 'tab': session.tab,
                            'what': session.what}
                if session.is_running else None,
                'user': users.current(),
                # (Signed in to Drive: its login is kept; whether it's still good is known when it's used)
                'drive': {'connected': os.path.exists(driveapi.TOKEN_PATH), 'reading': freshening.reading()},
                'phones': [dict(sources.describe(path), name=name, path=path) for name, path in sources.phones()],
                'replicas': [replica_info(path, known_replicas) for path in all_paths],
                'pairs': [pair_info(a, b, names, known_replicas) for a, b in known_replicas.pairs()],
                'inboxes': importing.inboxes()}

    def hash_replica(query, body):
        """Hash the local replica body['path'] asks for (as the replicas dashboard does), or pause it"""
        path = body.get('path', '')
        known_replicas = replicas.load()
        if path not in known_replicas.replica_paths() or paths.is_cloud_path(path) or not os.path.isdir(path):
            return {'ok': False}
        job = hashing.job_for(path)
        if body.get('pause') and job is not None:
            job.pause()
        else:
            from dirdelta.screens.hashes_screen import dashboard_actions
            dashboard_actions.start_hashing(path)
        return {'ok': True}

    def running(query, body):
        return {'running': session.is_running, 'user': session.user if session.is_running else None,
                'tab': session.tab if session.is_running else None}

    def user_list(query, body):
        return {'users': users.all_users(), 'current': users.current(), 'owner': users.OWNER,
                'email': settings.email_address()}

    def set_email(query, body):
        address = (body.get('address') or '').strip()
        if address.count('@') != 1 or ' ' in address:
            return {'ok': False, 'error': "That's not an email address."}
        settings.set_email_address(address)
        return {'ok': True}

    def add_user(query, body):
        name = (body.get('name') or '').strip().lower()
        try:
            users.add(name)
        except (users.UserError, OSError) as error:
            return {'ok': False, 'error': str(error)}
        return {'ok': True, 'name': name}

    return {('GET', '/api/home'): home, ('POST', '/api/home/hash'): hash_replica,
            ('GET', '/api/running'): running, ('GET', '/api/users'): user_list, ('POST', '/api/users/add'): add_user,
            ('POST', '/api/users/email'): set_email}
