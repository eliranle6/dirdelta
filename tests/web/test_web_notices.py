"""The emails the daemon's watcher sends (a replica's disk connected, a phone plugged in): none unless the user turned
that one on (known/settings.py's notices, web/daemon.py's _say())"""
import threading
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real settings left alone)
from dirdelta.known import settings
from dirdelta.known import users
from dirdelta.web import daemon
from dirdelta.web import watcher


class NoticesTest(unittest.TestCase):
    def say(self, kind):
        sent = []
        with mock.patch('dirdelta.sharing.link.email', side_effect=lambda url, what: sent.append(what) or 'sent'), \
                mock.patch.object(threading, 'Thread', side_effect=lambda target, daemon: mock.Mock(start=target)), \
                mock.patch.object(daemon, '_out'):
            daemon._say(kind, 'Black HD', 'key', 8765, [users.OWNER])
        return sent

    def test_nothing_is_emailed_unless_turned_on_each_kind_apart(self):
        for kind in settings.NOTIFY_KINDS:
            settings.set_notified(kind, False)
        self.assertEqual([], self.say(watcher.REPLICA) + self.say(watcher.PHONE))
        settings.set_notified('phone', True)
        self.assertEqual([], self.say(watcher.REPLICA))
        self.assertEqual(["Import the photos of Black HD"], self.say(watcher.PHONE))
        settings.set_notified('phone', False)


if __name__ == '__main__':
    unittest.main()
