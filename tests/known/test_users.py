"""dirdelta's users (known/users.py): each one's replicas, pairs and settings their own"""
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real caches and config aren't touched)
from dirdelta.known import replicas, settings, users
from dirdelta.web import access


class UsersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        for target, path in (('dirdelta.known.replicas.REPLICAS_FILE', 'replicas.json'),
                             ('dirdelta.known.settings.SETTINGS_FILE', 'settings.json')):
            patcher = mock.patch(target, os.path.join(self.temp, path))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_owner_keeps_the_files_where_they_were_and_another_user_has_their_own_beside_them(self):
        self.assertEqual(replicas.REPLICAS_FILE, users.own(replicas.REPLICAS_FILE, users.OWNER))
        self.assertEqual(os.path.join(self.temp, 'users', 'hagit', 'replicas.json'),
                         users.own(replicas.REPLICAS_FILE, 'hagit'))

    def test_each_users_pairs_and_settings_are_their_own(self):
        users.add('hagit')
        known = replicas.load()
        known.record('/mine', 'cloud/mine')
        replicas.save(known)
        settings.set_email_address('me@example.com')
        with users.acting_as('hagit'):
            self.assertEqual([], replicas.load().history)
            self.assertIsNone(settings.email_address())
            hers = replicas.load()
            hers.record('/hers', 'cloud/hers')
            replicas.save(hers)
        self.assertEqual([('/mine', 'cloud/mine')], replicas.load().history)
        with users.acting_as('hagit'):
            self.assertEqual([('/hers', 'cloud/hers')], replicas.load().history)

    def test_a_thread_acts_as_its_own_user_and_the_others_as_the_runs(self):
        users.add('hagit')
        seen = []
        with users.acting_as('hagit'):
            other = threading.Thread(target=lambda: seen.append(users.current()))
            other.start()
            other.join()
            self.assertEqual('hagit', users.current())
        self.assertEqual([users.OWNER], seen)

    def test_users_are_the_owner_then_the_ones_added_and_a_name_is_plain(self):
        users.add('hagit')
        users.add(users.OWNER)
        self.assertEqual([users.OWNER, 'hagit'], users.all_users())
        for name in ('../x', 'Hagit Levi', ''):
            with self.assertRaises(users.UserError):
                users.add(name)

    def test_a_browser_is_the_user_its_link_or_cookie_says_if_theres_one(self):
        users.add('hagit')
        self.assertEqual('hagit', access.user_of('/import?u=hagit', 'dirdelta_key=k'))
        self.assertEqual('hagit', access.user_of('/', 'dirdelta_key=k; dirdelta_user=hagit'))
        self.assertEqual(users.OWNER, access.user_of('/', 'dirdelta_user=nobody'))
        self.assertEqual(users.OWNER, access.user_of('/', None))


if __name__ == '__main__':
    unittest.main()
