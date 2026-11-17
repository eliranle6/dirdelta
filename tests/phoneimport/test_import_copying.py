"""Copying an import's files from its source (phoneimport/copying.py, store.py, sources.py)"""
import hashlib
import os
import shutil
import unittest

from dirdelta.phoneimport import copying, store
from import_support import ImportTest


class CopyingTest(ImportTest):
    def test_the_media_files_are_copied_wherever_they_are_with_their_sha1(self):
        self.write(self.source, 'DCIM/Camera/PXL_20260101_1.jpg', 'one')
        self.write(self.source, 'Pictures/Screenshots/s.png', 'two')
        self.write(self.source, 'Documents/notes.txt', 'not media')
        self.write(self.source, 'Android/data/app/cache.jpg', "an app's")
        found = store.create(self.source, self.dest)
        self.wait_for(copying.copy(found).thread)
        self.assertEqual({'DCIM/Camera/PXL_20260101_1.jpg', 'Pictures/Screenshots/s.png'}, set(found.files))
        with open(found.local_path('DCIM/Camera/PXL_20260101_1.jpg')) as copied:
            self.assertEqual('one', copied.read())
        self.assertEqual(hashlib.sha1(b'one').hexdigest(), found.files['DCIM/Camera/PXL_20260101_1.jpg']['sha1'])
        self.assertEqual('done', copying.copying_of(found.id).phase)

    def test_it_goes_on_where_it_was_and_is_kept_across_restarts(self):
        self.write(self.source, 'DCIM/a.jpg', 'a')
        found = store.create(self.source, self.dest)
        self.wait_for(copying.copy(found).thread)
        first_copy = os.stat(found.local_path('DCIM/a.jpg')).st_mtime_ns
        self.write(self.source, 'DCIM/b.jpg', 'b')
        again = store.load(found.id)
        self.wait_for(copying.copy(again).thread)
        self.assertEqual({'DCIM/a.jpg': store.COPIED, 'DCIM/b.jpg': store.COPIED},
                         {relpath: info['state'] for relpath, info in store.load(found.id).files.items()})
        self.assertEqual(first_copy, os.stat(again.local_path('DCIM/a.jpg')).st_mtime_ns)

    def test_a_source_thats_gone_waits_for_it_to_come_back(self):
        self.write(self.source, 'DCIM/a.jpg', 'a')
        found = store.create(self.source, self.dest)
        shutil.rmtree(self.source)
        copy = copying.copy(found)
        self.wait_for(copy.thread)
        self.assertEqual('waiting', copy.phase)
        self.write(self.source, 'DCIM/a.jpg', 'a')
        self.wait_for(copying.copy(found).thread)
        self.assertEqual(store.COPIED, found.files['DCIM/a.jpg']['state'])


if __name__ == '__main__':
    unittest.main()
