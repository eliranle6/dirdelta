"""Who may use the web version, and where it is: a key in its links (kept in WEB_FILE, so a link
stays good when the daemon restarts), checked on every request (in the address once, then a cookie),
and the computer's address on the local network"""
import json
import os
import secrets
import socket
import urllib.parse

WEB_FILE = os.path.expanduser('~/.config/dirdelta/web.json')
DEFAULT_PORT = 8765
COOKIE = 'dirdelta_key'
# How long a browser keeps the key (seconds)
COOKIE_AGE = 30 * 24 * 3600


def settings():
    """{'key': ..., 'port': ...}, made (and kept) the first time"""
    try:
        with open(WEB_FILE) as web_file:
            found = json.load(web_file)
        if isinstance(found, dict) and isinstance(found.get('key'), str) and found['key']:
            found.setdefault('port', DEFAULT_PORT)
            return found
    except (OSError, ValueError):
        pass
    found = {'key': secrets.token_urlsafe(12), 'port': DEFAULT_PORT}
    os.makedirs(os.path.dirname(WEB_FILE), exist_ok=True)
    with open(os.open(WEB_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as web_file:
        json.dump(found, web_file)
    return found


def is_allowed(key, path, cookie_header):
    """Whether a request for path (with its query) with cookie_header has the key"""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    if query.get('k') == [key]:
        return True
    cookies = [part.strip() for part in (cookie_header or '').split(';')]
    return '%s=%s' % (COOKIE, key) in cookies


def cookie(key):
    return '%s=%s; Path=/; Max-Age=%d; SameSite=Strict; HttpOnly' % (COOKIE, key, COOKIE_AGE)


def local_address():
    """The computer's address on its network (its route out's), or 127.0.0.1 without one. (Connecting
    a UDP socket sends nothing.)"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(('192.0.2.1', 9))
            return probe.getsockname()[0]
        except OSError:
            return '127.0.0.1'


def link(key, port, page='/', **query):
    """The address of page, with the key (and query), to open on another device"""
    query = dict(query, k=key)
    return 'http://%s:%d%s?%s' % (local_address(), port, page, urllib.parse.urlencode(query))
