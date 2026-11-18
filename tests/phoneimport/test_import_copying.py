"""Reading a source into its pool (phoneimport/copying.py, pool.py, store.py, sources.py)"""
import hashlib
import os
import shutil
import unittest

from dirdelta.phoneimport import copying, pool, sources, store
from import_support import ImportTest


class CopyingTest(ImportTest):
    def read(self, is_listing=True, relpaths=()):
        reading = copying.read(self.source, is_listing, relpaths)
        self.wait_for(reading.thread)
        return reading

    def test_its_media_files_are_listed_wherever_they_are_and_only_the_ones_asked_for_copied_and_hashed(self):
        self.write(self.source, 'Camera/PXL_20260101_1.jpg', 'one')
        self.write(self.source, 'Screenshots/s.png', 'two')
        self.write(self.source, 'notes.txt', 'not media')
        self.write(self.source, '.thumbnails/t.jpg', 'a thumbnail')
        found = store.create(self.source, self.dest)
        self.read()
        self.assertEqual({'Camera/PXL_20260101_1.jpg': store.PENDING, 'Screenshots/s.png': store.PENDING},
                         {relpath: info['state'] for relpath, info in found.files().items()})
        self.read(False, ['Camera/PXL_20260101_1.jpg'])
        with open(found.pool.local_path('Camera/PXL_20260101_1.jpg')) as copied:
            self.assertEqual('one', copied.read())
        self.assertEqual((store.COPIED, hashlib.sha1(b'one').hexdigest()),
                         (found.files()['Camera/PXL_20260101_1.jpg']['state'], found.files()['Camera/PXL_20260101_1.jpg']['sha1']))
        self.assertEqual(store.PENDING, found.files()['Screenshots/s.png']['state'])

    def test_the_imports_of_a_source_share_its_copies_and_hashes_and_theres_one_for_a_source_and_replica(self):
        self.write(self.source, 'Camera/a.jpg', 'a')
        first = store.create(self.source, self.dest)
        self.read(relpaths=[])
        self.read(False, ['Camera/a.jpg'])
        other_dest = os.path.join(self.temp, 'other')
        os.makedirs(other_dest)
        second = store.create(self.source, other_dest)
        self.assertEqual(store.COPIED, second.files()['Camera/a.jpg']['state'])
        self.assertIs(first, store.create(self.source, self.dest))

    def test_a_changed_file_is_read_again_and_whats_read_is_kept_across_restarts(self):
        self.write(self.source, 'Camera/a.jpg', 'a')
        self.write(self.source, 'Camera/b.jpg', 'b')
        found = store.create(self.source, self.dest)
        self.read()
        self.read(False, ['Camera/a.jpg', 'Camera/b.jpg'])
        os.utime(self.write(self.source, 'Camera/b.jpg', 'B'), (1, 1))
        self.read()
        pool._pools.clear()
        self.assertEqual({'Camera/a.jpg': store.COPIED, 'Camera/b.jpg': store.PENDING},
                         {relpath: info['state'] for relpath, info in found.files().items()})

    def test_a_source_thats_gone_waits_for_it_to_come_back(self):
        self.write(self.source, 'Camera/a.jpg', 'a')
        found = store.create(self.source, self.dest)
        self.read()
        shutil.rmtree(self.source)
        self.assertEqual('waiting', self.read(False, ['Camera/a.jpg']).phase)
        self.write(self.source, 'Camera/a.jpg', 'a')
        self.read(False)
        self.assertEqual(store.COPIED, found.files()['Camera/a.jpg']['state'])

    def test_ending_an_import_removes_its_sources_copies_unless_another_import_has_it(self):
        self.write(self.source, 'Camera/a.jpg', 'a')
        first = store.create(self.source, self.dest)
        other_dest = os.path.join(self.temp, 'other')
        os.makedirs(other_dest)
        second = store.create(self.source, other_dest)
        self.read()
        self.read(False, ['Camera/a.jpg'])
        copy = first.pool.local_path('Camera/a.jpg')
        first.end()
        self.assertTrue(os.path.exists(copy))
        self.assertIsNone(store.load(first.id))
        second.end()
        self.assertFalse(os.path.exists(copy))
        self.assertEqual([], store.all_imports())


class SourcesTest(unittest.TestCase):
    def test_a_phone_is_called_by_its_model_and_its_dir_by_its_path_in_the_storage(self):
        self.assertEqual('Pixel 8', sources.device_name('mtp:host=Google_Pixel_8_3A170DLJH002DN'))
        self.assertEqual('SAMSUNG Android', sources.device_name('mtp:host=SAMSUNG_Android_R58M12ABCDE'))
        path = os.path.join(sources.GVFS_DIR, 'mtp:host=Google_Pixel_8_3A170DLJH002DN', 'Internal shared storage', 'DCIM')
        self.assertEqual({'device': 'Pixel 8', 'inner': 'DCIM', 'full': path}, sources.describe(path))
        self.assertEqual({'device': None, 'inner': '/home/me/Pictures', 'full': '/home/me/Pictures'},
                         sources.describe('/home/me/Pictures'))


if __name__ == '__main__':
    unittest.main()
