"""Mounting a replica's disk from the web page (web/mounting.py): sudo without a password if it lets the user, else
the password the page asked for, on sudo's stdin"""
import subprocess
import unittest
from unittest import mock

import helpers  # noqa: F401  (the caches redirected)
from dirdelta.known import mounts
from dirdelta.known import replicas
from dirdelta.web import mounting

VOLUME = mounts.Mount('/mnt/win', '/dev/sda3', 'ntfs', 'rw', '', '9618289F1828807B', 'OS')
REPLICA = '/mnt/win/Users/me'


class MountingTest(unittest.TestCase):
    def setUp(self):
        self.mounted = False
        self.runs = []
        self.answers = []
        known = replicas.Replicas(history=[(REPLICA, 'cloud/me')])
        for target, value in [('dirdelta.known.replicas.load', mock.Mock(return_value=known)),
                              ('dirdelta.known.mounts.unmounted', lambda path: None if self.mounted else VOLUME),
                              ('dirdelta.known.mounts.is_connected', lambda volume: True),
                              ('dirdelta.known.mounts.read_only_lines_of', lambda path: []),
                              ('dirdelta.known.mounts.mount_command', lambda volume: ['sudo', 'mount', '/mnt/win']),
                              ('dirdelta.web.mounting.subprocess.run', self.fake_run)]:
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.route = mounting.routes()[('POST', '/api/replicas/mount')]

    def fake_run(self, command, input=None, **kwargs):
        """sudo as it answers: the next of self.answers (returncode, output); a success mounts it"""
        self.runs.append((command, input))
        code, output = self.answers.pop(0)
        self.mounted = self.mounted or code == 0
        return subprocess.CompletedProcess(command, code, output)

    def test_mounted_without_a_password_when_sudo_lets_the_user(self):
        self.answers = [(0, '')]
        self.assertEqual({'ok': True, 'readOnly': []}, self.route({}, {'path': REPLICA}))
        self.assertEqual(['sudo', '-n', 'mount', '/mnt/win'], self.runs[0][0])

    def test_asks_for_the_password_when_sudo_needs_one(self):
        self.answers = [(1, 'sudo: a password is required')]
        answer = self.route({}, {'path': REPLICA})
        self.assertEqual({'ok': False, 'needsPassword': True, 'command': 'sudo mount /mnt/win'}, answer)
        self.assertFalse(self.mounted)

    def test_the_password_goes_to_sudo_on_its_stdin_and_is_not_said_back(self):
        self.answers = [(0, '')]
        answer = self.route({}, {'path': REPLICA, 'password': 'secret'})
        self.assertTrue(answer['ok'])
        command, given = self.runs[0]
        self.assertEqual(['sudo', '-S'], command[:2])
        self.assertNotIn('secret', command)
        self.assertEqual('secret\n', given)
        self.assertNotIn('secret', repr(answer))

    def test_a_wrong_password_asks_again(self):
        self.answers = [(1, 'Sorry, try again.\nsudo: 1 incorrect password attempt')]
        answer = self.route({}, {'path': REPLICA, 'password': 'wrong'})
        self.assertTrue(answer['needsPassword'])
        self.assertEqual("That password isn't right.", answer['error'])

    def test_a_hibernated_windows_says_what_to_do(self):
        self.answers = [(14, 'The disk contains an unclean file system (0, 0).')]
        answer = self.route({}, {'path': REPLICA, 'password': 'secret'})
        self.assertFalse(answer['ok'])
        self.assertIn('Fast Startup', answer['error'])

    def test_a_disk_not_connected_is_not_mounted(self):
        with mock.patch('dirdelta.known.mounts.is_connected', lambda volume: False):
            answer = self.route({}, {'path': REPLICA, 'password': 'secret'})
        self.assertEqual({'ok': False, 'error': "Its disk isn't connected: plug it in first."}, answer)
        self.assertEqual([], self.runs)

    def test_only_a_known_local_replica(self):
        self.assertFalse(self.route({}, {'path': '/etc', 'password': 'secret'})['ok'])
        self.assertEqual([], self.runs)

    def test_a_command_without_sudo_is_tried_as_it_is_first(self):
        self.answers = [(1, "Error opening read-only '/dev/sda3': Permission denied"), (1, 'sudo: a password is required')]
        with mock.patch('dirdelta.known.mounts.mount_command', lambda volume: ['mount', '/mnt/win']):
            answer = self.route({}, {'path': REPLICA})
        self.assertEqual([['mount', '/mnt/win'], ['sudo', '-n', 'mount', '/mnt/win']], [command for command, _ in self.runs])
        self.assertTrue(answer['needsPassword'])


if __name__ == '__main__':
    unittest.main()
