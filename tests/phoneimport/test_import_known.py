"""Whether replicas have a file already (phoneimport/known.py), and where it may go (suggest.py)"""
import datetime
import hashlib
import unittest
from unittest import mock

from dirdelta.drive import drivecache
from dirdelta.hashes import hashcache
from dirdelta.phoneimport import known, suggest
from import_support import ImportTest

SHA1 = hashlib.sha1(b'photo').hexdigest()


class KnownTest(ImportTest):
    def test_a_local_replica_has_a_file_by_its_contents_whatever_its_name_or_else_by_name_and_size(self):
        renamed = self.write(self.dest, 'media/Family/2026/renamed.jpg', 'photo')
        hashcache.put(renamed, {'sha1': SHA1})
        self.write(self.dest, 'media/Misc/PXL_2.jpg', 'xx')
        found = known.Known([self.dest])
        self.assertEqual([(self.dest, 'media/Family/2026/renamed.jpg', known.SAME_CONTENTS)],
                         found.found('PXL_1.jpg', 5, SHA1))
        self.assertEqual([(self.dest, 'media/Misc/PXL_2.jpg', known.SAME_NAME_AND_SIZE)], found.found('PXL_2.jpg', 2))
        self.assertEqual([], found.found('PXL_3.jpg', 2))
        self.assertIn('media/Family/2026', found.dirs[self.dest])

    def test_a_file_of_the_same_name_and_size_but_another_hash_isnt_the_same(self):
        other = self.write(self.dest, 'media/PXL_1.jpg', 'other')
        hashcache.put(other, {'sha1': hashlib.sha1(b'other').hexdigest()})
        found = known.Known([self.dest])
        self.assertEqual([], found.found('PXL_1.jpg', 5, SHA1))
        self.assertEqual([(self.dest, 'media/PXL_1.jpg', known.SAME_NAME_AND_SIZE)], found.found('PXL_1.jpg', 5))

    def test_a_drive_replica_has_a_file_by_drives_hash(self):
        entries = [drivecache.Entry('', 'root', True, False, None, None, {}, None),
                   drivecache.Entry('photos/x.jpg', 'id', False, False, 5, None, {'sha1': SHA1}, None)]
        with mock.patch('dirdelta.drive.drivecache.entries', return_value=entries):
            found = known.Known(['cloud/me'])
            self.assertEqual([('cloud/me', 'photos/x.jpg', known.SAME_CONTENTS)], found.found('other.jpg', 9, SHA1))

    def test_a_replica_that_cant_be_read_is_said_not_failed_on(self):
        found = known.Known([self.dest + '/gone'])
        self.assertEqual([], found.found('x.jpg', 1))
        self.assertEqual(1, len(found.errors))


class SuggestTest(unittest.TestCase):
    def test_a_files_date_is_in_its_name_or_else_its_time(self):
        self.assertEqual(datetime.date(2026, 2, 24), suggest.date_of('DCIM/PXL_20260224_093727119.jpg'))
        self.assertEqual(datetime.date(2025, 4, 26), suggest.date_of('IMG-20250426-WA0001.jpg'))
        when = datetime.datetime(2024, 5, 6, 12).timestamp()
        self.assertEqual(datetime.date(2024, 5, 6), suggest.date_of('IMG_1234.JPG', when))
        self.assertIsNone(suggest.date_of('IMG_1234.JPG'))

    def test_where_that_days_photos_are_else_the_nearest_days_before(self):
        suggester = suggest.Suggester(['media/Trip/PXL_20260224_1.jpg', 'media/Trip/PXL_20260224_2.jpg',
                                       'media/Day/PXL_20260224_3.jpg', 'media/Family/PXL_20260210_1.jpg'])
        self.assertEqual(['media/Trip', 'media/Day'], suggester.suggest(datetime.date(2026, 2, 24)))
        self.assertEqual(['media/Family'], suggester.suggest(datetime.date(2026, 2, 20)))
        self.assertEqual([], suggester.suggest(datetime.date(2026, 2, 1)))


if __name__ == '__main__':
    unittest.main()
