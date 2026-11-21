"""The record each replica keeps of itself (known/selfrecords.py): written to it, taken from it, and the disparities
between it and dirdelta's file"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the real caches and settings left alone)
from dirdelta.known import replicanames
from dirdelta.known import replicas
from dirdelta.known import selfrecords
from dirdelta.trees import paths


class SelfRecordsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.known = replicas.Replicas(history=[(self.root, 'cloud/x')])
        self.key = replicanames.label_key(self.root)
        self.live = mock.patch('dirdelta.util.dryrun.DRYRUN', False)

    def record(self):
        with open(os.path.join(self.root, paths.META_DIR, selfrecords.RECORD_NAME)) as record:
            return json.load(record)

    def write_there(self, **record):
        os.makedirs(os.path.join(self.root, paths.META_DIR), exist_ok=True)
        with open(os.path.join(self.root, paths.META_DIR, selfrecords.RECORD_NAME), 'w') as written:
            json.dump(record, written)

    def test_a_replica_gets_its_record_live_not_in_a_dry_run(self):
        self.known.set_label(self.key, 'laptop')
        found = selfrecords.check(self.root, self.known)
        self.assertEqual((False, None), (found.kept, found.disparity))
        self.assertFalse(os.path.exists(os.path.join(self.root, paths.META_DIR)))
        with self.live:
            self.assertTrue(selfrecords.check(self.root, self.known).kept)
        record = self.record()
        self.assertEqual(('laptop', self.known.records[self.key]['id']), (record['name'], record['id']))

    def test_a_name_given_elsewhere_is_taken_where_its_not_known(self):
        self.write_there(id='abc', name='work laptop', look={'color': 'teal'})
        self.assertIsNone(selfrecords.check(self.root, self.known).disparity)
        self.assertEqual(('work laptop', {'color': 'teal'}), (self.known.labels[self.key], self.known.looks[self.key]))

    def test_a_name_changed_here_is_written_to_it(self):
        self.write_there(id='abc', name='laptop')
        selfrecords.check(self.root, self.known)
        self.known.set_label(self.key, 'my laptop')
        with self.live:
            self.assertIsNone(selfrecords.check(self.root, self.known).disparity)
        self.assertEqual(('my laptop', 'abc'), (self.record()['name'], self.record()['id']))

    def test_a_name_changed_in_the_replica_is_for_the_user_to_settle(self):
        self.write_there(id='abc', name='laptop')
        selfrecords.check(self.root, self.known)
        self.write_there(id='abc', name='renamed elsewhere')
        disparity = selfrecords.check(self.root, self.known).disparity
        self.assertEqual((selfrecords.CHANGED, 'laptop', 'renamed elsewhere'),
                         (disparity['kind'], disparity['here']['name'], disparity['there']['name']))
        # Settled: this file's written to it (live), or its taken here
        self.assertFalse(selfrecords.resolve(self.root, self.known, selfrecords.WRITE_MINE).kept)
        with self.live:
            self.assertTrue(selfrecords.resolve(self.root, self.known, selfrecords.WRITE_MINE).kept)
        self.assertEqual('laptop', self.record()['name'])
        self.write_there(id='abc', name='renamed elsewhere')
        selfrecords.resolve(self.root, self.known, selfrecords.TAKE_THEIRS)
        self.assertEqual('renamed elsewhere', self.known.labels[self.key])
        self.assertIsNone(selfrecords.check(self.root, self.known).disparity)

    def test_another_replicas_id_where_the_record_points_is_a_disparity(self):
        self.write_there(id='abc', name='laptop')
        selfrecords.check(self.root, self.known)
        self.write_there(id='xyz', name='laptop')
        disparity = selfrecords.check(self.root, self.known).disparity
        self.assertEqual((selfrecords.OTHER, 'abc', 'xyz'), (disparity['kind'], disparity['recordedId'], disparity['there']['id']))


if __name__ == '__main__':
    unittest.main()
