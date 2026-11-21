"""Two disks of one model (one label), mounted at the same mount point one after the other, are two replicas: each kept
by its identity (its UUID and its path on it), at its disk's mount while it's mounted, else at a placeholder
(known/mounts/volumes.py, known/located.py)"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real caches and settings left alone)
from dirdelta.known import mounts
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.known.mounts import volumes

GREY, BLACK = 'F474B7AA74B76DCC', '9E82B4C782B4A565'


class TwoDisksTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.target = os.path.join(self.tmpdir, 'media', 'My Passport')
        os.makedirs(os.path.join(self.target, 'eliran'))
        by_uuid, devices = os.path.join(self.tmpdir, 'by-uuid'), os.path.join(self.tmpdir, 'dev')
        os.makedirs(by_uuid)
        os.makedirs(devices)
        self.devices = {}
        for uuid, device in ((GREY, 'sdb1'), (BLACK, 'sdc1')):
            self.devices[uuid] = os.path.join(devices, device)
            open(self.devices[uuid], 'w').close()
            os.symlink(self.devices[uuid], os.path.join(by_uuid, uuid))
        self.table = os.path.join(self.tmpdir, 'mounts')
        self.mount(None)
        self.path = os.path.join(self.tmpdir, 'replicas.json')
        for patcher in (mock.patch('dirdelta.known.mounts.names.BY_UUID_DIR', by_uuid),
                        mock.patch('dirdelta.known.mounts.names.MOUNTS_TABLE', self.table),
                        mock.patch('dirdelta.known.replicas.REPLICAS_FILE', self.path),
                        mock.patch('dirdelta.known.mounts.current_mount', side_effect=self.current_mount)):
            patcher.start()
            self.addCleanup(patcher.stop)
        replicanames.forget()

    def mount(self, uuid):
        """The disk uuid mounted at the mount point (None: neither)"""
        self.mounted = uuid
        with open(self.table, 'w') as table:
            if uuid:
                table.write('%s %s fuseblk rw 0 0\n' % (self.devices[uuid], self.target.replace(' ', '\\040')))

    def current_mount(self, path):
        if self.mounted and os.path.realpath(path).startswith(self.target):
            return mounts.Mount(self.target, self.devices[self.mounted], 'ntfs', 'rw', '', self.mounted, 'My Passport')
        return None

    def write(self, content):
        with open(self.path, 'w') as written:
            json.dump(content, written)

    def test_each_disks_replica_is_on_its_disk_while_its_mounted_and_not_there_while_the_other_is(self):
        grey_id, black_id = 'uuid:%s:/eliran' % (GREY,), 'uuid:%s:/eliran' % (BLACK,)
        self.write({'replicas': [grey_id, black_id]})
        here = os.path.join(self.target, 'eliran')
        self.mount(BLACK)
        black_there, grey_away = replicas.load().added_replicas[1], replicas.load().added_replicas[0]
        self.assertEqual(here, black_there)
        self.assertEqual(volumes.placeholder(GREY, 'eliran'), grey_away)
        self.assertIsNotNone(mounts.unmounted(grey_away))
        self.assertEqual(grey_id, replicanames.identity(grey_away))
        self.mount(GREY)
        self.assertEqual([here, volumes.placeholder(BLACK, 'eliran')], replicas.load().added_replicas)
        # (The grey one's placeholder, once its disk is mounted, is where it is)
        self.assertIsNone(mounts.unmounted(grey_away))
        self.assertEqual(here, volumes.present(grey_away))

    def test_a_disk_mounted_later_keeps_its_one_name(self):
        self.write({'replicas': ['uuid:%s:/eliran' % (BLACK,)], 'labels': {'uuid:%s:/eliran' % (BLACK,): 'Black HD'}})
        self.assertEqual(['Black HD'], [replicanames.name(path) for path in replicas.load().added_replicas])
        self.mount(BLACK)
        self.assertEqual(['Black HD'], [replicanames.name(path) for path in replicas.load().added_replicas])

    def test_saving_keeps_each_by_its_disk(self):
        self.mount(BLACK)
        known = replicas.Replicas()
        known.add_replica(os.path.join(self.target, 'eliran'))
        known.add_replica(volumes.placeholder(GREY, 'eliran'))
        replicas.save(known)
        with open(self.path) as saved:
            self.assertEqual(['uuid:%s:/eliran' % (BLACK,), 'uuid:%s:/eliran' % (GREY,)], json.load(saved)['replicas'])

    def test_a_file_from_before_is_read_by_the_disk_each_path_was_seen_on(self):
        here = os.path.join(self.target, 'eliran')
        self.write({'replicas': [here], 'known': {'uuid:%s:/eliran' % (GREY,): {'paths': [here]}}})
        # (The black disk mounted where the grey one was: its dir isn't the grey one's replica)
        self.mount(BLACK)
        self.assertEqual([volumes.placeholder(GREY, 'eliran')], replicas.load().added_replicas)
        self.mount(GREY)
        self.assertEqual([here], replicas.load().added_replicas)


if __name__ == '__main__':
    unittest.main()
