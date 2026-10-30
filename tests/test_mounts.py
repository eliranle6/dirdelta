import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import mounts

WIN = mounts.Mount('/mnt/win', '/dev/sda3', 'ntfs', 'rw,relatime', 'rw,user_id=0,group_id=0,allow_other',
                   '9618289F1828807B', 'OS')
DISK = mounts.Mount('/media/disk', '/dev/sdb1', 'ext4', 'rw,relatime', 'rw,errors=remount-ro',
                    '54a5edf9', None)


def findmnt_json(target, source='/dev/sda3', fstype='fuseblk', uuid: 'str | None' = '9618289F1828807B',
                 label='OS'):
    return json.dumps({'filesystems': [{'target': target, 'source': source, 'fstype': fstype,
                                        'vfs-options': 'rw,relatime', 'fs-options': 'rw,allow_other',
                                        'uuid': uuid, 'label': label}]})


class MountsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.by_uuid = os.path.join(self.tmpdir, 'by-uuid')
        os.makedirs(self.by_uuid)
        # What's mounted now, and what each command says: {program: (exit code, output)}, or a
        # function of the command; the commands run are kept
        self.mounted = set()
        self.answers = {}
        self.commands = []
        for patcher in (mock.patch('dirdelta.mounts.MOUNTS_FILE', os.path.join(self.tmpdir, 'mounts.json')),
                        mock.patch('dirdelta.mounts.BY_UUID_DIR', self.by_uuid),
                        mock.patch('os.path.ismount', side_effect=lambda path: path in self.mounted),
                        mock.patch('subprocess.run', side_effect=self.fake_run),
                        mock.patch('dirdelta.messages.print_line')):
            patcher.start()
            self.addCleanup(patcher.stop)
        show = mock.patch('dirdelta.messages.show')
        self.show = show.start()
        self.addCleanup(show.stop)

    def fake_run(self, command, **_):
        self.commands.append(command)
        program = command[1] if command[0] == 'sudo' else command[0]
        if program == 'findmnt' and '--fstab' in command:
            program = 'fstab'
        answer = self.answers.get(program, (1, ''))
        if callable(answer):
            answer = answer(command)
        return subprocess.CompletedProcess(command, answer[0], stdout=answer[1])

    def connect(self, mount):
        open(os.path.join(self.by_uuid, mount.uuid), 'w').close()

    def keep(self, *kept):
        mounts.save({mount.target: mount for mount in kept})

    # Remembering

    def test_remembers_a_volume_by_its_devices_type(self):
        self.answers['findmnt'] = (0, findmnt_json('/mnt/win'))
        self.answers['lsblk'] = (0, 'ntfs\n')
        mounts.remember('/mnt/win/Users')
        self.assertEqual(mounts.load(), {'/mnt/win': mounts.Mount('/mnt/win', '/dev/sda3', 'ntfs', 'rw,relatime',
                                                                  'rw,allow_other', '9618289F1828807B', 'OS')})

    def test_doesnt_remember_the_root_filesystem_one_without_a_uuid_or_a_cloud_path(self):
        self.answers['findmnt'] = (0, findmnt_json('/', fstype='ext4'))
        mounts.remember('/home/x')
        self.answers['findmnt'] = (0, findmnt_json('/tmp', source='tmpfs', fstype='tmpfs', uuid=None))
        mounts.remember('/tmp/x')
        mounts.remember('cloud/eliran')
        self.assertEqual(mounts.load(), {})
        self.assertFalse(os.path.exists(mounts.MOUNTS_FILE))

    def test_without_findmnt_nothing_is_remembered(self):
        self.answers['findmnt'] = lambda command: (_ for _ in ()).throw(FileNotFoundError('findmnt'))
        mounts.remember('/mnt/win')
        self.assertEqual(mounts.load(), {})

    def test_a_broken_file_is_an_error(self):
        with open(mounts.MOUNTS_FILE, 'w') as f:
            f.write('{')
        with self.assertRaises(mounts.MountsError):
            mounts.load()

    # Finding it unmounted

    def test_the_innermost_kept_mount_is_checked(self):
        inner = DISK._replace(target='/mnt/win/inner')
        self.keep(WIN, inner)
        self.mounted = {'/mnt/win'}
        self.assertEqual(mounts.unmounted('/mnt/win/inner/x'), inner)
        self.assertIsNone(mounts.unmounted('/mnt/win/x'))
        self.assertIsNone(mounts.unmounted('/mnt/window'))
        self.mounted = set()
        self.assertEqual(mounts.unmounted('/mnt/win'), WIN)

    # Mounting

    def test_a_mounted_one_isnt_asked_about(self):
        self.keep(WIN)
        self.mounted = {'/mnt/win'}
        with mock.patch('dirdelta.picker.pick_option', side_effect=AssertionError('asked')):
            self.assertTrue(mounts.ensure_mounted('/mnt/win/x'))
            self.assertTrue(mounts.ensure_mounted('/elsewhere'))

    def test_going_back(self):
        self.keep(WIN)
        self.connect(WIN)
        with helpers.answering_option_picker([mounts.BACK]):
            self.assertFalse(mounts.ensure_mounted('/mnt/win/x'))
        self.assertEqual(self.commands, [['findmnt', '--fstab', '-no', 'OPTIONS', '--mountpoint', '/mnt/win']])

    def test_mounting_by_uuid(self):
        self.keep(WIN)
        self.connect(WIN)
        self.answers['mount'] = lambda command: self.mounted.add('/mnt/win') or (0, '')
        with helpers.answering_option_picker([mounts.MOUNT]) as pick:
            self.assertTrue(mounts.ensure_mounted('/mnt/win/x'))
        self.assertIn("/mnt/win isn't mounted (last time: /dev/sda3, ntfs, 'OS')", pick.call_args[1]['header'])
        self.assertEqual(pick.call_args[0][0][0],
                         'Mount it (runs: sudo mount -t ntfs -o rw UUID=9618289F1828807B /mnt/win)')
        # Not NTFS's FUSE options
        self.assertEqual(self.commands[-1], ['sudo', 'mount', '-t', 'ntfs', '-o', 'rw', 'UUID=9618289F1828807B',
                                             '/mnt/win'])

    def test_an_unconnected_disk_is_waited_for(self):
        self.keep(DISK)
        self.answers['mount'] = lambda command: self.mounted.add('/media/disk') or (0, '')
        headers = []

        def pick_option(options, header):
            headers.append(header)
            if len(headers) == 2:
                # Connected before the second try
                self.connect(DISK)
            return mounts.TRY_AGAIN if mounts.TRY_AGAIN in options else options[0]
        with mock.patch('dirdelta.picker.pick_option', side_effect=pick_option):
            self.assertTrue(mounts.ensure_mounted('/media/disk'))
        self.assertIn("isn't connected", headers[0])
        self.assertIn("isn't connected", headers[1])
        self.assertIn("Mount it?", headers[2])

    def test_a_failed_mount_is_said_and_asked_again(self):
        self.keep(DISK)
        self.connect(DISK)
        self.answers['mount'] = (32, 'mount: /media/disk: mount point does not exist.\n')
        with helpers.answering_option_picker([mounts.MOUNT, mounts.BACK]):
            self.assertFalse(mounts.ensure_mounted('/media/disk'))
        title, lines = self.show.call_args[0][:2]
        self.assertEqual(title, "Cannot mount /media/disk")
        self.assertIn('mount: /media/disk: mount point does not exist.', lines)

    def test_unclean_ntfs_says_what_to_do(self):
        self.keep(WIN)
        self.connect(WIN)
        self.answers['mount'] = (14, 'The disk contains an unclean file system (0, 0).\n'
                                     'Metadata kept in Windows cache, refused to mount.\n')
        with helpers.answering_option_picker([mounts.MOUNT, mounts.BACK]):
            self.assertFalse(mounts.ensure_mounted('/mnt/win'))
        # Not read-only instead
        self.assertEqual([command for command in self.commands if 'mount' in command],
                         [['sudo', 'mount', '-t', 'ntfs', '-o', 'rw', 'UUID=9618289F1828807B', '/mnt/win']])
        title, lines = self.show.call_args[0][:2]
        self.assertEqual(title, "Cannot mount /mnt/win")
        self.assertIn("shut it down fully", lines[-1])

    # The command

    def test_a_volume_in_fstab_is_mounted_by_its_line(self):
        self.answers['fstab'] = (0, 'noauto,user\n')
        self.assertEqual(mounts.mount_command(DISK), ['mount', '/media/disk'])
        self.answers['fstab'] = (0, 'defaults\n')
        self.assertEqual(mounts.mount_command(DISK), ['sudo', 'mount', '/media/disk'])

    def test_read_write_with_the_filesystems_options(self):
        self.assertEqual(mounts.mount_command(DISK),
                         ['sudo', 'mount', '-t', 'ext4', '-o', 'rw,errors=remount-ro', 'UUID=54a5edf9', '/media/disk'])
        # Even if it was read-only
        self.assertEqual(mounts.mount_command(DISK._replace(vfs_options='ro,relatime', fs_options='ro')),
                         ['sudo', 'mount', '-t', 'ext4', '-o', 'rw', 'UUID=54a5edf9', '/media/disk'])

if __name__ == '__main__':
    unittest.main()
