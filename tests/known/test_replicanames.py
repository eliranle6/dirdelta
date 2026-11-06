import os
import tempfile
import unittest
from unittest import mock

from dirdelta.known import mounts
from dirdelta.known import replicanames
from dirdelta.known import replicas

MOUNT = mounts.Mount('/mnt/disk', '/dev/sdb1', 'ext4', 'rw', '', 'AAAA-1234', None)


class NamesTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        for name, patcher in (('file', mock.patch('dirdelta.known.replicas.REPLICAS_FILE', os.path.join(self.tmpdir.name, 'r.json'))),
                              ('mount', mock.patch('dirdelta.known.mounts.current_mount', return_value=MOUNT)),
                              ('user', mock.patch('dirdelta.drive.drivecache.user', return_value='me')),
                              ('root', mock.patch('dirdelta.drive.drivecache.root_id', return_value='ROOT'))):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        replicanames.forget()
        self.addCleanup(replicanames.forget)

    def label(self, path, label):
        known = replicas.Replicas()
        known.set_label(replicanames.label_key(path), label)
        replicas.save(known)

    def test_a_local_one_says_its_disk(self):
        self.assertEqual(replicanames.full('/mnt/disk/eliran'), 'LocalDisk(234):/mnt/disk/eliran')

    def test_a_local_one_on_no_known_disk(self):
        self.mount.return_value = None
        self.assertEqual(replicanames.full('/x'), 'LocalDisk:/x')

    def test_a_drive_one_says_its_user(self):
        self.assertEqual(replicanames.full('cloud/eliran'), 'Cloud(me):/eliran')
        self.user.return_value = None
        self.assertEqual(replicanames.full('cloud/eliran'), 'Cloud:/eliran')

    def test_a_replicas_label_is_its_own_not_its_disks(self):
        self.label('/mnt/disk/a', 'blue WD')
        self.assertEqual(replicanames.labeled('/mnt/disk/a'), 'blue WD:/mnt/disk/a')
        self.assertEqual(replicanames.labeled('/mnt/disk/b'), '/mnt/disk/b')
        self.assertEqual(replicanames.label('/mnt/disk/b'), None)

    def test_a_label_stays_wherever_its_disk_is_mounted(self):
        self.label('/mnt/disk/a', 'mine')
        self.mount.return_value = MOUNT._replace(target='/media/other')
        replicanames.forget()
        self.assertEqual(replicanames.label('/media/other/a'), 'mine')

    def test_a_drive_ones_label_is_its_own(self):
        self.label('cloud/a', 'photos')
        self.assertEqual(replicanames.full('cloud/a'), 'photos')
        self.assertEqual(replicanames.short_names(['cloud/a'])['cloud/a'], 'photos')
        self.assertEqual(replicanames.full('cloud/b'), 'Cloud(me):/b')

    def test_a_label_changed_in_the_file_is_seen(self):
        self.label('/mnt/disk/a', 'one')
        self.assertEqual(replicanames.label('/mnt/disk/a'), 'one')
        self.label('/mnt/disk/a', 'another')
        self.assertEqual(replicanames.label('/mnt/disk/a'), 'another')

if __name__ == '__main__':
    unittest.main()
