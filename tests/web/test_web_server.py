"""The web version's server (web/server.py, web/access.py) and its watcher (web/watcher.py)"""
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import helpers  # noqa: F401 (the real caches and settings left alone)
from dirdelta.web import access, server
from dirdelta.web.watcher import PHONE, Watcher


class ServerTest(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir)
        patcher = mock.patch.object(access, 'WEB_FILE', os.path.join(temp_dir, 'web.json'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key = access.settings()['key']
        self.video = os.path.join(temp_dir, 'v.mp4')
        with open(self.video, 'wb') as video:
            video.write(b'0123456789')
        routes = {('GET', '/api/hello'): lambda query, body: {'hello': query.get('name')},
                  ('POST', '/api/echo'): lambda query, body: body,
                  ('GET', '/api/file'): lambda query, body: server.FileReply(self.video)}
        self.server = server.serve(routes, self.key, '127.0.0.1', 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:%d' % (self.server.server_address[1],)

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}), timeout=5)

    def test_without_the_key_nothing_is_served(self):
        for path in ('/', '/api/hello', '/app.js'):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.get(path)
            self.assertEqual(403, raised.exception.code)

    def test_the_link_sets_the_key_as_a_cookie_for_what_comes_after(self):
        page = self.get('/?k=' + self.key)
        self.assertIn(b'<title>dirdelta</title>', page.read())
        cookie = page.headers['Set-Cookie'].split(';')[0]
        answer = json.load(self.get('/api/hello?name=me', {'Cookie': cookie}))
        self.assertEqual({'hello': 'me'}, answer)

    def test_the_key_is_kept_for_the_next_start(self):
        self.assertEqual(self.key, access.settings()['key'])

    def test_files_outside_the_pages_arent_served(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get('/../web/server.py?k=' + self.key)
        self.assertEqual(404, raised.exception.code)


    def test_a_file_is_sent_whole_or_the_range_asked_for_as_a_browsers_video_asks(self):
        whole = self.get('/api/file?k=' + self.key)
        self.assertEqual((200, b'0123456789', 'video/mp4'), (whole.status, whole.read(), whole.headers['Content-Type']))
        for asked, status, part in (('bytes=2-4', 206, b'234'), ('bytes=7-', 206, b'789'), ('bytes=-3', 206, b'789')):
            answer = self.get('/api/file?k=' + self.key, {'Range': asked})
            self.assertEqual((status, part), (answer.status, answer.read()), asked)
        self.assertEqual('bytes 2-4/10', self.get('/api/file?k=' + self.key, {'Range': 'bytes=2-4'}).headers['Content-Range'])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get('/api/file?k=' + self.key, {'Range': 'bytes=20-'})
        self.assertEqual(416, raised.exception.code)


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.there = {}
        self.said = []
        self.watcher = Watcher(lambda *args: self.said.append(args), look=lambda: dict(self.there))

    def test_what_appears_is_said_once_but_not_what_was_there_at_the_start(self):
        self.there['/old'] = (PHONE, 'old phone')
        self.watcher.check(now=0)
        self.there['/phone'] = (PHONE, 'Pixel')
        self.watcher.check(now=5)
        self.watcher.check(now=10)
        self.assertEqual([(PHONE, 'Pixel', '/phone')], self.said)

    def test_a_flaky_link_is_said_again_only_after_a_quiet_while(self):
        self.watcher.check(now=0)
        for now in (5, 15, 25):
            self.there['/phone'] = (PHONE, 'Pixel')
            self.watcher.check(now=now)
            del self.there['/phone']
            self.watcher.check(now=now + 1)
        self.there['/phone'] = (PHONE, 'Pixel')
        self.watcher.check(now=5 + 600)
        self.assertEqual(2, len(self.said))


if __name__ == '__main__':
    unittest.main()
