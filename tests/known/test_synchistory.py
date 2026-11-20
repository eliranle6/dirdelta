"""Each replica's sync history, kept in its meta dir: written live only, read back, the last sync found"""
import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401 (the caches' fakes)
from dirdelta.known import log_entries
from dirdelta.known import replicas
from dirdelta.known import synchistory
from dirdelta.sync import dirsync_main


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirstuff-history-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_a_live_sync_is_appended_and_the_last_one_found(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            synchistory.record(self.root, synchistory.entry('cloud/a', 'a on Cloud', 'copied 2 files'))
            synchistory.record(self.root, synchistory.entry('cloud/a', 'a on Cloud', ''))
        self.assertEqual([item['changed'] for item in synchistory.read(self.root)], ['copied 2 files', ''])
        self.assertEqual(synchistory.last_sync(self.root)['changed'], '')
        self.assertTrue(os.path.exists(os.path.join(self.root, 'meta', synchistory.HISTORY_NAME)))

    def test_a_dry_run_writes_nothing(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            synchistory.record(self.root, synchistory.entry('cloud/a', 'a', 'copied 2 files'))
        self.assertFalse(os.path.exists(os.path.join(self.root, 'meta')))
        self.assertIsNone(synchistory.last_sync(self.root))

    def test_a_drive_replicas_is_kept_in_its_meta_folder_in_drive(self):
        kept = {}
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), \
                mock.patch('dirdelta.drive.drivemeta.files.read_text', side_effect=lambda folder, name: kept.get((folder, name))), \
                mock.patch('dirdelta.drive.drivemeta.files.write_text', side_effect=lambda folder, name, text: kept.update({(folder, name): text})):
            synchistory.record('cloud/eliran', synchistory.entry('/disk/eliran', 'eliran on disk', 'removed 1 file'))
            synchistory.record('cloud/eliran', synchistory.entry('/disk/eliran', 'eliran on disk', ''))
            self.assertEqual(len(synchistory.read('cloud/eliran')), 2)
        self.assertIn(('/eliran', synchistory.HISTORY_NAME), kept)
        self.assertEqual(json.loads(kept[('/eliran', synchistory.HISTORY_NAME)].splitlines()[0])['changed'], 'removed 1 file')


class SyncNotedTest(unittest.TestCase):
    """A sync's end notes it in both replicas' histories"""

    def setUp(self):
        self.a, self.b = (tempfile.mkdtemp(prefix='dirstuff-history-%s-' % (name,)) for name in 'ab')
        for path in (self.a, self.b):
            self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        self.trees = [(mock.Mock(displayname=lambda: self.a), self.a), (mock.Mock(displayname=lambda: self.b), self.b)]
        self.known = replicas.Replicas()
        self.known.note_compared(self.a, self.b, 0, 3, datetime.datetime(2026, 11, 20, 9, 0))
        self.changes = log_entries.Changes()
        self.changes.note(self.b, 'copied', 3, self.a)

    def test_each_replica_notes_the_other_and_what_changed_in_it(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False):
            dirsync_main.note_in_history(self.trees, self.changes, self.known)
        in_a, in_b = synchistory.last_sync(self.a), synchistory.last_sync(self.b)
        self.assertEqual((in_a['with'], in_a['changed'], in_a['only']['there']), (self.b, '', 3))
        self.assertEqual((in_b['with'], in_b['changed'], in_b['only']['here']), (self.a, 'copied 3 files from %s' % (self.a,), 3))

    def test_a_dry_runs_sync_isnt_noted(self):
        with mock.patch('dirdelta.util.dryrun.DRYRUN', True):
            dirsync_main.note_in_history(self.trees, self.changes, self.known)
        self.assertIsNone(synchistory.last_sync(self.a))
