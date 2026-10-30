import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta import localdiskdirtree
from dirdelta import mounts
from dirdelta import replicalog
from dirdelta import replicas

LOG = """15.12.2025 - copied DCIM pictures from old pixel 8 (not whatsapp pictures)
17.05.2026 - removed old money.ods
             remove Resume.* files
"""


class ParseTest(unittest.TestCase):
    def test_entries_and_their_lines(self):
        self.assertEqual(replicalog.parse(LOG), [
            replicalog.Entry(datetime.date(2025, 12, 15), "copied DCIM pictures from old pixel 8 (not whatsapp pictures)"),
            replicalog.Entry(datetime.date(2026, 5, 17), "removed old money.ods\nremove Resume.* files")])

    def test_a_bare_date_and_lines_it_cant_parse(self):
        self.assertEqual(replicalog.parse("the log\n1.2.2024\n32.13.2024 - not a date\n\n3.2.2024 -  x\n"), [
            replicalog.Entry(None, "the log"),
            replicalog.Entry(datetime.date(2024, 2, 1), "32.13.2024 - not a date"),
            replicalog.Entry(datetime.date(2024, 2, 3), "x")])

    def test_the_last_entry_is_the_latest(self):
        self.assertEqual(replicalog.last_entry(LOG).date, datetime.date(2026, 5, 17))
        self.assertEqual(replicalog.last_entry("2.1.2026 - b\n1.1.2026 - a\n").text, "b")
        self.assertIsNone(replicalog.last_entry("no dates here\n"))

    def test_an_entry_is_added_at_the_end(self):
        line = replicalog.entry_line(datetime.date(2026, 10, 30), "copied 2 files from cloud/eliran")
        self.assertEqual(line, "30.10.2026 - copied 2 files from cloud/eliran")
        self.assertEqual(replicalog.with_entry("a\nb", line), "a\nb\n" + line + "\n")
        self.assertEqual(replicalog.with_entry("", line), line + "\n")


class IdentityTest(unittest.TestCase):
    def test_a_local_replica_by_its_filesystem_and_the_path_in_it(self):
        mount = mounts.Mount('/mnt/win', '/dev/sda3', 'ntfs', 'rw', '', 'UUID1', 'OS')
        with mock.patch('dirdelta.mounts.current_mount', return_value=mount), \
                mock.patch('os.path.realpath', side_effect=lambda path: path):
            self.assertEqual(replicalog.identity('/mnt/win/Users/eliran'), 'uuid:UUID1:/Users/eliran')
            self.assertEqual(replicalog.identity('/mnt/win'), 'uuid:UUID1:/')
        with mock.patch('dirdelta.mounts.current_mount', return_value=None):
            self.assertEqual(replicalog.identity('/tmp'), 'path:%s' % (os.path.realpath('/tmp'),))

    def test_a_drive_replica_by_the_account_and_its_path(self):
        with mock.patch('dirdelta.drivecache.root_id', return_value='ROOT'):
            self.assertEqual(replicalog.identity('cloud//eliran/'), 'drive:ROOT:/eliran')

    def test_whether_its_disk_is_connected(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        open(os.path.join(tmpdir, 'UUID1'), 'w').close()
        with mock.patch('dirdelta.mounts.BY_UUID_DIR', tmpdir):
            self.assertTrue(replicalog.is_disk_connected('uuid:UUID1:/x'))
            self.assertFalse(replicalog.is_disk_connected('uuid:UUID2:/x'))
            self.assertTrue(replicalog.is_disk_connected('drive:ROOT:/eliran'))
        self.assertEqual(replicalog.disk_uuid('uuid:UUID1:/x'), 'UUID1')


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.tree = localdiskdirtree.LocalDiskDirTree(self.tmpdir, silent=True)

    def test_a_local_log(self):
        self.assertIsNone(replicalog.read(self.tree))
        replicalog.write(self.tree, LOG)
        self.assertEqual(replicalog.read(self.tree), LOG)
        self.assertEqual(os.listdir(self.tmpdir), [replicalog.LOG_NAME])

    def test_a_drive_log_is_downloaded_once(self):
        tree = mock.Mock(spec=replicalog.clouddirtree.CloudDirTree)
        tree.has_file.return_value = True
        tree.file_size.return_value = len(LOG)
        tree.displayname.return_value = 'cloud/eliran'

        def fetch(relpath, local_path):
            with open(local_path, 'w') as f:
                f.write(LOG)
        tree.fetch_file.side_effect = fetch
        self.assertEqual(replicalog.read(tree), LOG)
        self.assertEqual(replicalog.read(tree), LOG)
        self.assertEqual(tree.fetch_file.call_count, 1)
        # Written: uploaded in its place
        written = []
        tree.write_file.side_effect = lambda relpath, local_path: written.append((relpath, open(local_path).read()))
        replicalog.write(tree, LOG + "x\n")
        self.assertEqual(written, [(replicalog.LOG_NAME, LOG + "x\n")])

    def test_a_drive_replica_without_a_log(self):
        tree = mock.Mock(spec=replicalog.clouddirtree.CloudDirTree)
        tree.has_file.return_value = False
        self.assertIsNone(replicalog.read(tree))


class ChangesTest(unittest.TestCase):
    def test_what_changed_in_each_replica_added_up(self):
        changes = replicalog.Changes()
        changes.note('/b', 'copied', 2, 'cloud/a')
        changes.note('cloud/a', 'removed', 1)
        changes.note('/b', 'copied', 10, 'cloud/a')
        changes.note('/b', 'moved', 0)
        self.assertEqual(changes.paths(), ['/b', 'cloud/a'])
        self.assertEqual(changes.summary('/b'), "copied 12 files from cloud/a")
        self.assertEqual(changes.summary('cloud/a'), "removed 1 file")
        self.assertEqual(changes.summary('/c'), "")


class LogEntriesTest(unittest.TestCase):
    """After a sync that changed a replica, an entry for its last_update.txt is offered"""
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.a, self.b = (os.path.join(self.tmpdir, name) for name in 'ab')
        for path in (self.a, self.b):
            os.makedirs(path)
        with open(os.path.join(self.b, replicalog.LOG_NAME), 'w') as log:
            log.write("1.1.2026 - started\n")
        self.trees = [(localdiskdirtree.LocalDiskDirTree(path, silent=True), path) for path in (self.a, self.b)]
        self.known = replicas.Replicas()
        self.changes = replicalog.Changes()
        self.changes.note(self.b, 'copied', 2, self.a)
        self.changes.note(self.b, 'removed', 1)
        for patcher in (mock.patch('dirdelta.replicas.save'), mock.patch('dirdelta.messages.show'),
                        mock.patch('dirdelta.replicalog.identity', side_effect=lambda path: 'id:' + path),
                        mock.patch('dirdelta.interactive_dir_sync.is_writable', return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.today = datetime.date.today().strftime('%d.%m.%Y')

    def log(self, path):
        log_path = os.path.join(path, replicalog.LOG_NAME)
        if not os.path.exists(log_path):
            return None
        with open(log_path) as log:
            return log.read()

    def offer(self, answers, edited=None):
        with helpers.answering_option_picker(answers) as pick, \
                mock.patch('dirdelta.messages.ask', return_value=edited):
            replicalog.offer_entries(self.changes, self.trees, self.known)
        return pick

    def test_added_to_the_changed_replicas_log(self):
        pick = self.offer(["Add it to its last_update.txt (%s)" % (self.b,)])
        line = "%s - copied 2 files from %s; removed 1 file" % (self.today, self.a)
        self.assertIn(line, pick.call_args.kwargs['header'])
        self.assertEqual(self.log(self.b), "1.1.2026 - started\n" + line + "\n")
        self.assertIsNone(self.log(self.a))
        info = self.known.known['id:' + self.b]
        self.assertEqual(info['last_entry']['text'], "copied 2 files from %s; removed 1 file" % (self.a,))
        self.assertIsNotNone(info['changed'])
        replicalog.replicas.save.assert_called_with(self.known)

    def test_to_both_replicas_edited_first_one_made(self):
        self.offer([replicalog.EDIT_ENTRY, "Add it to both"], edited="copied the trip's photos")
        line = "%s - copied the trip's photos\n" % (self.today,)
        self.assertTrue(self.log(self.b).endswith(line))
        self.assertEqual(self.log(self.a), line)

    def test_none_added_but_its_change_is_known(self):
        self.offer([replicalog.NO_ENTRY])
        self.assertEqual(self.log(self.b), "1.1.2026 - started\n")
        self.assertIsNotNone(self.known.known['id:' + self.b]['changed'])

    def test_nothing_changed_nothing_offered(self):
        with mock.patch('dirdelta.picker.pick_option', side_effect=AssertionError('asked')):
            replicalog.offer_entries(replicalog.Changes(), self.trees, self.known)
        replicalog.replicas.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
