"""The import's tests' fixture (ImportTest): its imports, a source and a replica in temp dirs"""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import helpers
from dirdelta.phoneimport import store


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        patcher = mock.patch.object(store, 'IMPORTS_DIR', os.path.join(self.temp, 'imports'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = os.path.join(self.temp, 'phone')
        self.dest = os.path.join(self.temp, 'replica')
        os.makedirs(self.source)
        os.makedirs(self.dest)

    def write(self, root, relpath, contents):
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as found:
            found.write(contents)
        return path

    def wait_for(self, thread):
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def wait_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            if time.monotonic() > deadline:
                self.fail("It didn't happen")
            time.sleep(0.01)


__all__ = ['ImportTest', 'helpers']
