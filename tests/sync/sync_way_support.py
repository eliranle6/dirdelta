"""What a sync's way's tests share: its names, and a sync of two local dirs"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.sync.way import interactive_dir_sync
from dirdelta.trees import localdiskdirtree


Sync = interactive_dir_sync.InteractiveDirSync
YES = Sync.CONFIRM_YES
NO = Sync.CONFIRM_NO
SURE = Sync.CONFIRM_SURE
NOTHING = Sync.NOTHING


class TwoDirsTestCase(unittest.TestCase):
    """A sync of two local dirs"""

    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-ask-'))
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.src_path, self.dst_path = os.path.join(self.tmpdir, 'src'), os.path.join(self.tmpdir, 'dst')
        helpers.make_files(self.src_path, ['a.txt', 'b.txt', 'c.txt'])
        helpers.make_files(self.dst_path, ['old/d.txt'])
        for patcher in (mock.patch('dirdelta.ui.messages.print_line'), mock.patch('dirdelta.ui.messages.print_progress'),
                        mock.patch('dirdelta.ui.messages.show'), mock.patch('dirdelta.ui.messages.ask', return_value='do it')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sync = Sync(localdiskdirtree.LocalDiskDirTree(self.src_path, silent=True),
                         localdiskdirtree.LocalDiskDirTree(self.dst_path, silent=True))


if __name__ == '__main__':
    unittest.main()
