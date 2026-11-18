"""The web version's HTTP server (serve()): the page's files (static/), and the API's routes, each
request checked for the key (see access.py)"""
import json
import mimetypes
import os
import posixpath
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dirdelta.ui.picker import updates
from dirdelta.web import access

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
# The pages, by path (the rest of static/ is served by its name)
PAGES = {'/': 'home.html', '/sync': 'sync.html', '/run': 'app.html', '/import': 'import.html'}


class Reply(object):
    """A route's answer that isn't JSON: bytes of a type (with is_kept, the browser may keep them)"""
    def __init__(self, data, content_type, status=200, is_kept=False):
        self.data, self.content_type, self.status, self.is_kept = data, content_type, status, is_kept


class FileReply(object):
    """A route's answer that's a file (path): sent a part at a time, a range of it if asked (as a
    browser's video asks for)"""
    def __init__(self, path, content_type=None):
        self.path = path
        self.content_type = content_type or mimetypes.guess_type(path)[0] or 'application/octet-stream'


def serve(routes, key, host, port):
    """A server at host:port (not yet serving: call its serve_forever()) for routes (see api.routes())"""
    class Handler(_Handler):
        pass
    Handler.routes, Handler.key = routes, key
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


class _Handler(BaseHTTPRequestHandler):
    routes, key = {}, None

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def _handle(self, method):
        if not access.is_allowed(self.key, self.path, self.headers.get('Cookie')):
            return self._send(403, 'text/plain', b'This page needs its link (with its key).')
        parts = urllib.parse.urlsplit(self.path)
        query = {name: values[-1] for name, values in urllib.parse.parse_qs(parts.query).items()}
        route = self.routes.get((method, parts.path))
        try:
            if route is not None:
                body = {}
                if method == 'POST':
                    length = int(self.headers.get('Content-Length') or 0)
                    body = json.loads(self.rfile.read(length) or b'{}')
                answer = route(query, body)
                if isinstance(answer, FileReply):
                    return self._send_file(answer)
                if isinstance(answer, Reply):
                    return self._send(answer.status, answer.content_type, answer.data, is_kept=answer.is_kept)
                return self._send(200, 'application/json', json.dumps(answer).encode())
            if method == 'GET':
                return self._static(parts.path)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception:
            updates.log_error()
            return self._send(500, 'text/plain', b'Something went wrong: see ~/.cache/dirdelta/errors.log')
        return self._send(404, 'text/plain', b'Not found')

    def _static(self, path):
        name = PAGES.get(path, posixpath.normpath(path).lstrip('/'))
        file_path = os.path.join(STATIC_DIR, name)
        if name.startswith('..') or not os.path.isfile(file_path):
            return self._send(404, 'text/plain', b'Not found')
        with open(file_path, 'rb') as static_file:
            data = static_file.read()
        content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        # A page's link has the key: kept as a cookie, for the requests after it
        return self._send(200, content_type, data, set_cookie=path in PAGES)

    def _send(self, status, content_type, data, set_cookie=False, is_kept=False):
        self.send_response(status)
        self.send_header('Content-Type', content_type + ('; charset=utf-8' if content_type.startswith('text') or
                                                          content_type.endswith(('json', 'javascript')) else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'private, max-age=86400' if is_kept else 'no-store')
        if set_cookie:
            self.send_header('Set-Cookie', access.cookie(self.key))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, answer):
        try:
            sent = open(answer.path, 'rb')
        except OSError:
            return self._send(404, 'text/plain', b'Not found')
        with sent:
            size = os.fstat(sent.fileno()).st_size
            start, end = 0, size - 1
            wanted = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
            if wanted and not (wanted.group(1) or wanted.group(2)):
                wanted = None
            if wanted:
                if wanted.group(1):
                    start = int(wanted.group(1))
                    end = min(int(wanted.group(2)), size - 1) if wanted.group(2) else size - 1
                else:
                    start = max(size - int(wanted.group(2)), 0)
                if start > end:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % size)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return None
            self.send_response(206 if wanted else 200)
            self.send_header('Content-Type', answer.content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if wanted:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            self.send_header('Cache-Control', 'private, max-age=86400')
            self.end_headers()
            sent.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = sent.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        return None

    def log_message(self, format, *args):
        pass
